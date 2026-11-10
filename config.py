"""
config.py — Central configuration and environment variable loading
for the Confluence Document Creation Agent.
"""

from __future__ import annotations

import os
from typing import List, Optional
from dotenv import load_dotenv

# Load .env if present
load_dotenv()


# ── LLM Provider ──────────────────────────────────────────────────────────────

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "bedrock").lower()

# AWS Bedrock
AWS_ACCESS_KEY_ID: Optional[str] = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_SESSION_TOKEN: Optional[str] = os.getenv("AWS_SESSION_TOKEN")
AWS_REGION: str = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "eu-west-1"))
BEDROCK_MODEL_ID: str = os.getenv("BEDROCK_MODEL_ID", "eu.anthropic.claude-opus-4-7")
BEDROCK_MAX_TOKENS: int = int(os.getenv("BEDROCK_MAX_TOKENS", os.getenv("MAX_OUTPUT_TOKENS", "4096")))

# OpenAI
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Anthropic
ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

# Google Gemini
GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL: str = os.getenv("GOOGLE_MODEL", "gemini-flash-lite-latest")

# Limits & Timeouts
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "2500"))
LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))


# ── Amazon OpenSearch Configuration ───────────────────────────────────────────

OPENSEARCH_ENDPOINT: Optional[str] = os.getenv("OPENSEARCH_ENDPOINT")
OPENSEARCH_INDEX_SOURCES: str = os.getenv("OPENSEARCH_INDEX_SOURCES", "confluence-agent-sources")
OPENSEARCH_INDEX_DOCS: str = os.getenv("OPENSEARCH_INDEX_DOCS", "confluence-agent-documents")
OPENSEARCH_USERNAME: Optional[str] = os.getenv("OPENSEARCH_USERNAME")
OPENSEARCH_PASSWORD: Optional[str] = os.getenv("OPENSEARCH_PASSWORD")
OPENSEARCH_USE_SSL: bool = os.getenv("OPENSEARCH_USE_SSL", "true").lower() in ("true", "1", "yes")
OPENSEARCH_VERIFY_CERTS: bool = os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() in ("true", "1", "yes")


# ── Atlassian MCP Client Configuration ────────────────────────────────────────

ATLASSIAN_MCP_ENABLED: bool = os.getenv("ATLASSIAN_MCP_ENABLED", "true").lower() in ("true", "1", "yes")
ATLASSIAN_MCP_URL: str = os.getenv("ATLASSIAN_MCP_URL", "https://mcp.atlassian.com/v2/mcp")
ATLASSIAN_SITE_URL: str = os.getenv("ATLASSIAN_SITE_URL", "https://lay-shah.atlassian.net")
ATLASSIAN_DEFAULT_SPACE_ID: str = os.getenv("ATLASSIAN_DEFAULT_SPACE_ID", "65679")
ATLASSIAN_MCP_TIMEOUT_SECONDS: float = float(os.getenv("ATLASSIAN_MCP_TIMEOUT_SECONDS", "30"))
ATLASSIAN_AUTH_TYPE: str = os.getenv("ATLASSIAN_AUTH_TYPE", "oauth").lower()
ATLASSIAN_USER_EMAIL: Optional[str] = os.getenv("ATLASSIAN_USER_EMAIL", "")
ATLASSIAN_CLOUD_ID: Optional[str] = os.getenv("ATLASSIAN_CLOUD_ID", "94a84124-201f-4391-8b99-969090375bf9")
CONFLUENCE_DEFAULT_SPACE: Optional[str] = os.getenv("CONFLUENCE_DEFAULT_SPACE", "Dev")
CONFLUENCE_PARENT_PAGE_ID: Optional[str] = os.getenv("CONFLUENCE_PARENT_PAGE_ID")


# ── Helpers & Validation ──────────────────────────────────────────────────────

def is_atlassian_mcp_enabled() -> bool:
    """Return True if Atlassian MCP is enabled."""
    return ATLASSIAN_MCP_ENABLED


def get_provider_model() -> str:
    """Return model identifier for the active LLM provider."""
    if LLM_PROVIDER == "bedrock":
        return BEDROCK_MODEL_ID
    if LLM_PROVIDER == "openai":
        return OPENAI_MODEL
    if LLM_PROVIDER == "anthropic":
        return ANTHROPIC_MODEL
    if LLM_PROVIDER == "google":
        return GOOGLE_MODEL
    return "unknown"


def validate_config() -> List[str]:
    """Validate active provider and basic environment settings."""
    errors: List[str] = []
    if LLM_PROVIDER == "bedrock":
        # Bedrock can use IAM roles, CLI profile, or explicit keys
        pass
    elif LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is not set.")
    elif LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set.")
    elif LLM_PROVIDER == "google" and not GOOGLE_API_KEY:
        errors.append("GOOGLE_API_KEY is not set.")
    return errors

