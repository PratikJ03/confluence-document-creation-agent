"""
mcp_confluence.py — Atlassian Model Context Protocol (MCP) Client for Confluence operations.

Handles:
- Connecting to official Atlassian Rovo MCP v2 endpoint (https://mcp.atlassian.com/v2/mcp).
- Creating Confluence pages via MCP JSON-RPC tool calls (`createConfluenceContent`).
- Session management with initialize → notifications/initialized → tool calls.
- Mock mode support for offline testing and dev runs.

Connection technique adapted from a proven working implementation against the same
Atlassian site (lay-shah.atlassian.net).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

import config
from auth_atlassian import AtlassianAuthManager

logger = logging.getLogger(__name__)


class ConfluenceMCPClient:
    """
    MCP Client specialized for Confluence document creation and publishing.

    Key implementation details (matching the proven working pattern):
    - cloudId = the Atlassian site URL (e.g. "https://lay-shah.atlassian.net"), NOT a UUID
    - parent = {"spaceId": "<numeric-space-id>"}, NOT a spaceKey string
    - body = {"format": "markdown", "value": content}, NOT HTML storage format
    - Session lifecycle: initialize → notifications/initialized → tools/call
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        auth_manager: Optional[AtlassianAuthManager] = None,
    ) -> None:
        self.server_url = server_url or config.ATLASSIAN_MCP_URL
        self.auth = auth_manager or AtlassianAuthManager()
        self.enabled = config.is_atlassian_mcp_enabled()
        self._session_id: Optional[str] = None
        self._request_counter: int = 0
        self._mock_pages: List[Dict[str, Any]] = []
        self._mock_mode = False

    def set_mock_pages(self, pages: List[Dict[str, Any]]) -> None:
        """Allow unit tests to mock page existence without network access."""
        self._mock_pages = pages
        self._mock_mode = True

    # ── Low-level MCP transport ───────────────────────────────────────────────

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers including Bearer token and optional session ID."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.auth.get_auth_header(),
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    def _send_jsonrpc(
        self,
        method: str,
        params: Dict[str, Any],
        *,
        expect_response: bool = True,
    ) -> Dict[str, Any]:
        """
        Send a JSON-RPC 2.0 request to the Atlassian MCP v2 endpoint.
        Parses SSE `data:` lines from the response body.
        """
        if not self.auth.is_authenticated:
            raise RuntimeError("Atlassian authentication required. Please connect in sidebar.")

        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        # Notifications (no "id") don't expect a response body
        if expect_response:
            payload["id"] = self._next_id()

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.server_url, data=data, headers=self._get_headers())

        try:
            with urllib.request.urlopen(req, timeout=config.ATLASSIAN_MCP_TIMEOUT_SECONDS) as resp:
                # Capture session ID from response header
                new_session_id = resp.headers.get("Mcp-Session-Id")
                if new_session_id:
                    self._session_id = new_session_id

                raw_body = resp.read().decode("utf-8", errors="ignore")

                if not expect_response:
                    return {}

                # Parse SSE format: look for "data:" lines containing JSON
                return self._parse_sse(raw_body)

        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                pass

            # Parse MCP-level error from 403 body
            if error_body:
                try:
                    err_json = json.loads(error_body)
                    err_msg = err_json.get("error", {}).get("message", "")
                    if err_msg:
                        raise RuntimeError(
                            f"Atlassian MCP error ({exc.code}): {err_msg}"
                        ) from exc
                except (json.JSONDecodeError, AttributeError):
                    pass

            self.auth.handle_auth_error(exc.code, exc.reason)
            raise RuntimeError(
                f"Atlassian MCP HTTP {exc.code}: {error_body[:300] or exc.reason}"
            ) from exc

    @staticmethod
    def _parse_sse(resp_text: str) -> Dict[str, Any]:
        """Parse Server-Sent Events response from Atlassian MCP."""
        for line in resp_text.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                if raw.startswith(("{", "[")):
                    return json.loads(raw)
        # Fallback: try parsing entire body as plain JSON
        try:
            return json.loads(resp_text)
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _extract_json_content(result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the first JSON object returned in an MCP text content block."""
        content_list = result.get("content", [])
        if not isinstance(content_list, list):
            return {}
        for block in content_list:
            if not isinstance(block, dict):
                continue
            text = block.get("text", "")
            if not text:
                continue
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, json.JSONDecodeError):
                continue
        return {}

    # ── MCP Session Lifecycle ─────────────────────────────────────────────────

    def _initialize_session(self) -> None:
        """
        Perform the MCP session handshake:
        1. Send `initialize` request → capture Mcp-Session-Id from response header
        2. Send `notifications/initialized` notification
        """
        # Step 1: Initialize
        self._session_id = None  # Force fresh session
        self._send_jsonrpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "Confluence-Document-Creation-Agent",
                    "version": "1.0.0",
                },
            },
        )
        logger.info("MCP session initialized (session_id=%s)", self._session_id)

        # Step 2: Send initialized notification (no response expected)
        self._send_jsonrpc(
            "notifications/initialized",
            {},
            expect_response=False,
        )

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call an MCP tool by name with given arguments.
        Handles session initialization automatically.
        """
        # Ensure session is active
        if not self._session_id:
            self._initialize_session()

        resp = self._send_jsonrpc("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result", {})

        # Check for MCP-level errors in the tool result
        if result.get("isError"):
            content_list = result.get("content", [])
            err_text = ""
            for block in content_list:
                if isinstance(block, dict) and block.get("type") == "text":
                    err_text = block.get("text", "")
                    break
            raise RuntimeError(f"MCP tool '{name}' returned error: {err_text}")

        return result

    # ── Confluence Page Creation ──────────────────────────────────────────────

    def create_page(
        self,
        title: str,
        content_markdown: str,
        space_key: str,
        parent_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publish a new Confluence page via Atlassian MCP.

        Uses the proven working pattern:
        - cloudId = site URL (e.g. "https://lay-shah.atlassian.net")
        - parent = {"spaceId": "<numeric>"} or {"parentContentId": "<id>"}
        - body = {"format": "markdown", "value": <content>}
        - contentType = "page"
        """
        if not self.enabled:
            raise RuntimeError("Atlassian MCP is disabled in configuration.")

        # Mock mode for testing
        if self._mock_mode:
            mock_id = f"mock-page-{len(self._mock_pages) + 101}"
            mock_url = f"https://atlassian.net/wiki/spaces/{space_key}/pages/{mock_id}/{title.replace(' ', '+')}"
            res = {
                "id": mock_id,
                "title": title,
                "space_key": space_key,
                "url": mock_url,
                "status": "created (mock)",
            }
            self._mock_pages.append(res)
            return res

        if not self.auth.is_authenticated:
            raise RuntimeError(
                "Atlassian is not authenticated. Connect a valid OAuth session before publishing."
            )

        # cloudId = the Atlassian site URL (proven working pattern)
        cloud_id = config.ATLASSIAN_SITE_URL

        # Build parent destination
        # Uses numeric spaceId (e.g. "65679"), NOT space key
        if parent_page_id:
            parent_dest: Dict[str, Any] = {"parentContentId": str(parent_page_id)}
        else:
            # Use the configured numeric space ID
            space_id = config.ATLASSIAN_DEFAULT_SPACE_ID
            if not space_id:
                raise RuntimeError(
                    "ATLASSIAN_DEFAULT_SPACE_ID is not configured. "
                    "Set the numeric Confluence space ID in .env."
                )
            parent_dest = {"spaceId": str(space_id)}

        # Build the createConfluenceContent arguments
        # Key: body format is "markdown" (NOT html storage format)
        arguments: Dict[str, Any] = {
            "cloudId": cloud_id,
            "parent": parent_dest,
            "contentType": "page",
            "title": title.strip(),
            "body": {
                "format": "markdown",
                "value": content_markdown,
            },
        }

        logger.info(
            "Creating Confluence page '%s' in space ID %s via MCP (cloudId=%s)",
            title,
            parent_dest.get("spaceId", parent_dest.get("parentContentId")),
            cloud_id,
        )

        try:
            result = self.call_tool("createConfluenceContent", arguments)
        except RuntimeError as exc:
            msg = str(exc)
            if "scope" in msg.lower() or "re-authorize" in msg.lower():
                raise RuntimeError(
                    "Atlassian MCP requires additional OAuth scopes. "
                    "Run `atlassian-mcp-auth clear` then `atlassian-mcp-auth login` "
                    "to re-authorize with full write scopes."
                ) from exc
            raise RuntimeError(f"Confluence page creation failed: {exc}") from exc

        # Extract page ID and URL from the MCP response
        content_data = self._extract_json_content(result)

        page_id = (
            content_data.get("data", {}).get("id")
            or content_data.get("id")
            or content_data.get("pageId")
        )
        page_url = (
            content_data.get("data", {}).get("url")
            or content_data.get("url")
            or content_data.get("webUrl")
            or content_data.get("data", {}).get("webUrl")
        )

        if not page_url and page_id:
            page_url = f"{cloud_id}/wiki/spaces/{space_key}/pages/{page_id}"

        if not page_id and not page_url:
            logger.warning("MCP response did not contain page ID or URL: %s", result)
            # Return what we have — the page may still have been created
            page_url = f"{cloud_id}/wiki/spaces/{space_key}"

        return {
            "id": page_id or "created",
            "title": title,
            "space_key": space_key,
            "url": page_url,
            "status": "published",
        }

    # ── Jira Issue Operations ──────────────────────────────────────────────────

    def create_jira_issue(
        self,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new issue on the specified Jira project via Atlassian MCP.
        Uses the official 'createJiraIssue' tool.
        """
        if not self.enabled:
            raise RuntimeError("Atlassian MCP is disabled in configuration.")

        # Mock mode for testing
        if self._mock_mode:
            mock_key = f"{project_key}-10{len(self._mock_pages) + 1}"
            mock_url = f"{config.ATLASSIAN_SITE_URL}/browse/{mock_key}"
            return {
                "key": mock_key,
                "summary": summary,
                "project_key": project_key,
                "issue_type": issue_type,
                "priority": priority,
                "url": mock_url,
                "status": "created (mock)",
            }

        if not self.auth.is_authenticated:
            raise RuntimeError(
                "Atlassian is not authenticated. Connect a valid OAuth session before creating Jira issues."
            )

        cloud_id = config.ATLASSIAN_SITE_URL

        arguments: Dict[str, Any] = {
            "cloudId": cloud_id,
            "projectKey": project_key.strip().upper(),
            "summary": summary.strip(),
            "issueType": issue_type,
            "description": description or "",
            "contentFormat": "markdown",
            "priority": priority,
        }
        if labels:
            arguments["labels"] = [l.strip() for l in labels if l.strip()]

        logger.info(
            "Creating Jira issue in project '%s' (%s: '%s') via MCP",
            project_key,
            issue_type,
            summary,
        )

        try:
            result = self.call_tool("createJiraIssue", arguments)
        except RuntimeError as exc:
            msg = str(exc)
            if "scope" in msg.lower() or "re-authorize" in msg.lower():
                raise RuntimeError(
                    "Atlassian MCP requires write scopes for Jira. "
                    "Please re-authenticate via the sidebar with full write scopes."
                ) from exc
            raise RuntimeError(f"Jira issue creation failed: {exc}") from exc

        content_data = self._extract_json_content(result)

        issue_key = (
            content_data.get("data", {}).get("key")
            or content_data.get("key")
            or content_data.get("issueKey")
        )
        issue_url = (
            content_data.get("data", {}).get("url")
            or content_data.get("url")
            or content_data.get("self")
        )

        if not issue_url and issue_key:
            issue_url = f"{cloud_id}/browse/{issue_key}"

        if not issue_key and not issue_url:
            logger.warning("MCP response did not contain issue key or URL: %s", result)
            issue_url = f"{cloud_id}/jira/your-work"

        return {
            "key": issue_key or "created",
            "summary": summary,
            "project_key": project_key,
            "issue_type": issue_type,
            "priority": priority,
            "url": issue_url,
            "status": "created",
        }

