"""
tests/test_document_generator.py — Tests for the Confluence Document Orchestrator.
"""

from unittest.mock import MagicMock
from auth_atlassian import AtlassianAuthManager
from document_generator import ConfluenceDocumentOrchestrator
from mcp_confluence import ConfluenceMCPClient
from opensearch_service import OpenSearchService


def test_prepare_document_preview_validation_failure():
    orch = ConfluenceDocumentOrchestrator()
    preview = orch.prepare_document_preview(
        topic="",
        source_content="Short",
        size="medium",
        space="",
    )
    assert preview["success"] is False
    assert preview["stage"] == "validation"
    assert len(preview["errors"]) >= 3


def test_prepare_document_preview_flow(monkeypatch):
    orch = ConfluenceDocumentOrchestrator()

    # Mock the LLM generation call to avoid network calls during unit test
    def mock_gen(*args, **kwargs):
        return {
            "title": kwargs.get("topic", "Test Doc"),
            "content_markdown": "# Test Doc\n\nExecutive summary based on reference [Source 1]. Implementation details [Source 2].",
            "provider": "bedrock",
            "model": "amazon.nova-micro-v1:0",
            "source_passages": kwargs.get("passages", []),
        }

    monkeypatch.setattr("document_generator.generate_confluence_document", mock_gen)

    preview = orch.prepare_document_preview(
        topic="Disaster Recovery Strategy",
        source_content="Passage one outlines RTO and RPO goals of under 1 hour for Tier 1 databases.\n\nPassage two describes warm standby replication to secondary AWS region.",
        size="short",
        space="DEV",
    )

    assert preview["success"] is True
    assert preview["stage"] == "preview"
    assert preview["quality_report"]["has_citations"] is True
    assert len(preview["retrieved_passages"]) > 0


def test_publish_confirmed_document(monkeypatch):
    orch = ConfluenceDocumentOrchestrator()
    # Enable mock pages in MCP client
    orch.mcp.set_mock_pages([])

    result = orch.publish_confirmed_document(
        topic="Disaster Recovery Strategy",
        document_markdown="# Document text",
        space="DEV",
    )

    assert result["success"] is True
    assert result["status"] == "published_and_indexed"
    assert "https://" in result["page_url"]
    assert result["opensearch_doc_id"] is not None
