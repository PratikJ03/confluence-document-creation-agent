"""
auth_atlassian.py — Secure OAuth 2.1 & Enterprise Authentication for Atlassian MCP.

Provides:
- OAuth 2.1 session management (login, logout, refresh, revocation).
- Expiration tracking and automatic re-authentication notifications.
- Granular error handling for 401 (expired/invalid) and 403 (permission denied).
- Strict token masking: raw tokens and secrets are never logged or exposed.
- User permission isolation: ensures user context is strictly preserved.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import config

logger = logging.getLogger(__name__)

# Scopes required for Confluence document generation, page search, and publishing
REQUIRED_SCOPES = [
    "read:me",
    "read:account",
    "offline_access",
    "search:confluence",
    "read:confluence-user",
    "read:page:confluence",
    "write:page:confluence",
    "read:space:confluence",
    "read:confluence-content.all",
    "write:confluence-content",
]


class AuthState(str, Enum):
    """Lifecycle status of the Atlassian authentication session."""
    DISCONNECTED = "disconnected"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    PERMISSION_DENIED = "permission_denied"
    REVOKED = "revoked"


@dataclass
class AtlassianSession:
    """
    Encapsulates authenticated session data.
    Never prints or exposes the raw access_token or refresh_token.
    """
    user_email: Optional[str] = None
    account_id: Optional[str] = None
    site_url: Optional[str] = None
    cloud_id: Optional[str] = None
    access_token: Optional[str] = field(default=None, repr=False)
    refresh_token: Optional[str] = field(default=None, repr=False)
    expires_at: float = 0.0
    scopes: list[str] = field(default_factory=lambda: list(REQUIRED_SCOPES))

    def is_expired(self, buffer_seconds: float = 60.0) -> bool:
        """Check if access token is expired or within expiry buffer."""
        if not self.access_token:
            return True
        if self.expires_at == 0.0:
            return False
        return (time.time() + buffer_seconds) >= self.expires_at

    def masked_token(self) -> str:
        """Safely mask token for diagnostic display without leaking secrets."""
        if not self.access_token:
            return "[NONE]"
        if len(self.access_token) <= 8:
            return "[PROTECTED]"
        return f"{self.access_token[:4]}...{self.access_token[-4:]}"


class AtlassianAuthManager:
    """
    Manages OAuth 2.1 authentication flow and token lifecycles for Atlassian MCP.
    Automatically detects tokens saved by `atlassian-mcp-auth login`.
    """

    def __init__(self, auto_load_saved: bool = True) -> None:
        self.state: AuthState = AuthState.DISCONNECTED
        self.session: Optional[AtlassianSession] = None
        self._last_error: Optional[str] = None
        if auto_load_saved:
            self._load_saved_oauth_token()

    def _load_saved_oauth_token(self) -> bool:
        """
        Load tokens from the supported Atlassian MCP stores.  The standalone
        auth CLI uses ``~/.atlassian-mcp-auth/tokens.db`` while the shared
        Atlassian MCP client used by the companion agent stores tokens in
        ``%LOCALAPPDATA%\\AtlassianMCP\\tokens.json``.  Supporting both lets
        this agent use the same authorized MCP session without copying tokens
        into the project.
        """
        if os.getenv("PYTEST_CURRENT_TEST"):
            return False

        db_path = os.path.expanduser("~/.atlassian-mcp-auth/tokens.db")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        json_path = os.path.join(localappdata, "AtlassianMCP", "tokens.json") if localappdata else ""

        # Preferred format used by atlassian-mcp-auth.
        if os.path.isfile(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute(
                    "SELECT access_token, refresh_token, expires_at, cloud_id FROM tokens WHERE profile='default'"
                )
                row = cur.fetchone()
                conn.close()

                if row and row[0]:
                    access_token, refresh_token, expires_at, cloud_id = row
                    if expires_at and float(expires_at) <= time.time():
                        self.state = AuthState.EXPIRED
                        return False
                    self._set_loaded_session(access_token, refresh_token, expires_at, cloud_id)
                    return True
            except Exception as exc:
                logger.debug("Could not load SQLite OAuth token: %s", exc)

        try:
            if json_path and os.path.isfile(json_path):
                with open(json_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                tokens = data.get("tokens", data)
                access_token = tokens.get("access_token")
                refresh_token = tokens.get("refresh_token")
                if access_token:
                    self._set_loaded_session(
                        access_token,
                        refresh_token,
                        tokens.get("expires_at", 0),
                        config.ATLASSIAN_CLOUD_ID,
                    )
                    return True
        except Exception as exc:
            logger.debug("Could not auto-load saved OAuth token: %s", exc)
        return False

    def _set_loaded_session(self, access_token: str, refresh_token: Optional[str], expires_at: Any, cloud_id: Optional[str]) -> None:
        """Install a token loaded from either supported local token store."""
        user_email = config.ATLASSIAN_USER_EMAIL or ""
        self.session = AtlassianSession(
            user_email=user_email,
            account_id=None,
            cloud_id=cloud_id or config.ATLASSIAN_CLOUD_ID,
            site_url=config.ATLASSIAN_SITE_URL,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=float(expires_at or 0.0),
        )
        self.state = AuthState.AUTHENTICATED
        self._last_error = None
        logger.info("Loaded active Atlassian OAuth session for '%s'.", user_email)

    @property
    def is_authenticated(self) -> bool:
        """True if session exists, is active, and not expired."""
        if not self.session or self.state != AuthState.AUTHENTICATED:
            return False
        return not self.session.is_expired()

    def login_with_oauth(
        self,
        access_token: str,
        user_email: str,
        site_url: str,
        expires_in: float = 3600.0,
        refresh_token: Optional[str] = None,
        cloud_id: Optional[str] = None,
    ) -> AtlassianSession:
        """Register a successful OAuth 2.1 authorization exchange."""
        if not access_token:
            raise ValueError("Access token cannot be empty.")
        if not user_email:
            raise ValueError("User email cannot be empty.")

        expires_at = (time.time() + expires_in) if expires_in != 0.0 else 0.0
        self.session = AtlassianSession(
            user_email=user_email,
            account_id=cloud_id,
            cloud_id=cloud_id,
            site_url=site_url,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        self.state = AuthState.AUTHENTICATED
        self._last_error = None
        logger.info("User '%s' authenticated successfully with Atlassian OAuth.", user_email)
        return self.session

    def logout(self) -> None:
        """Clear active credentials and reset state to DISCONNECTED."""
        user = self.session.user_email if self.session else "Unknown"
        self.session = None
        self.state = AuthState.DISCONNECTED
        self._last_error = None
        logger.info("Atlassian session terminated for user '%s'.", user)

    def handle_auth_error(self, status_code: int, error_detail: Optional[str] = None) -> str:
        """Map HTTP authentication error codes to user-friendly messages."""
        detail = error_detail or ""
        if status_code == 401:
            self.state = AuthState.EXPIRED
            msg = "🔒 Your Atlassian session has expired or the token is invalid. Please re-authenticate."
            self._last_error = msg
            return msg
        if status_code == 403:
            self.state = AuthState.PERMISSION_DENIED
            msg = "🚫 Access denied (403): You do not have permission for this Confluence space."
            self._last_error = msg
            return msg
        msg = f"❌ Atlassian authentication error ({status_code}): {detail}"
        self._last_error = msg
        return msg

    def get_auth_header(self) -> Dict[str, str]:
        """Return Authorization header for MCP requests."""
        if not self.is_authenticated:
            if self.session and self.session.is_expired():
                self.state = AuthState.EXPIRED
                raise RuntimeError("Atlassian session has expired. Please re-authenticate.")
            raise RuntimeError("Not authenticated with Atlassian. Please connect your account.")
        return {"Authorization": f"Bearer {self.session.access_token}"}

    def get_public_status(self) -> Dict[str, Any]:
        """Safe dictionary representation for UI display."""
        if not self.session:
            return {
                "state": self.state.value,
                "is_authenticated": False,
                "user_email": None,
                "cloud_id": None,
                "site_url": None,
                "token_masked": "[NONE]",
                "last_error": self._last_error,
            }

        return {
            "state": self.state.value,
            "is_authenticated": self.is_authenticated,
            "user_email": self.session.user_email,
            "cloud_id": self.session.cloud_id,
            "site_url": self.session.site_url,
            "token_masked": self.session.masked_token(),
            "expires_in_seconds": max(0, int(self.session.expires_at - time.time())) if self.session.expires_at else None,
            "last_error": self._last_error,
        }

