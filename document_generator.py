"""
document_generator.py — End-to-end orchestrator for Confluence Document Creation.

Follows the required 11-step pipeline:
1. Input validation.
2. OpenSearch source storage & indexing.
3. OpenSearch relevant passage retrieval.
4. Grounded document generation via Amazon Bedrock / LLM.
5. Hallucination prevention & citation enforcement.
6. Document length and coverage validation.
7. Return preview payload for user approval.
8. (User Confirmation in UI)
9. Atlassian MCP Confluence page publishing.
10. Retrieve and display page URL.
11. Final document indexing in OpenSearch.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import config
from auth_atlassian import AtlassianAuthManager
from llm_service import generate_confluence_document
from mcp_confluence import ConfluenceMCPClient
from opensearch_service import OpenSearchService
from validators import validate_document_output, validate_input

logger = logging.getLogger(__name__)


class ConfluenceDocumentOrchestrator:
    """
    Coordinates the pipeline between OpenSearch, Bedrock, and Atlassian MCP.
    """

    def __init__(
        self,
        opensearch_svc: Optional[OpenSearchService] = None,
        mcp_client: Optional[ConfluenceMCPClient] = None,
        auth_mgr: Optional[AtlassianAuthManager] = None,
    ) -> None:
        self.auth = auth_mgr or AtlassianAuthManager()
        self.opensearch = opensearch_svc or OpenSearchService()
        self.mcp = mcp_client or ConfluenceMCPClient(auth_manager=self.auth)

    def prepare_document_preview(
        self,
        topic: str,
        source_content: str,
        size: str,
        space: str,
        parent_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes Steps 1 to 7:
        Validates input -> Indexes source in OpenSearch -> Retrieves relevant passages ->
        Generates grounded document via Bedrock -> Validates length & citations ->
        Returns complete preview for user confirmation.
        """
        # Step 1: Input Validation
        validation_errors = validate_input(topic, source_content, size, space)
        if validation_errors:
            return {
                "success": False,
                "stage": "validation",
                "errors": validation_errors,
            }

        # Step 2: Store & index source content in OpenSearch
        source_id = self.opensearch.index_source_content(topic, source_content)

        # Step 3: Retrieve only relevant passages
        retrieved_passages = self.opensearch.retrieve_relevant_passages(topic, source_id=source_id, top_k=5)
        if not retrieved_passages:
            return {
                "success": False,
                "stage": "retrieval",
                "errors": ["Failed to extract and index passages from source content."],
            }

        # Step 4 & 5: Generate structured document using Amazon Bedrock with strict grounding
        llm_result = generate_confluence_document(
            topic=topic,
            passages=retrieved_passages,
            size=size,
            space_key=space,
        )

        doc_markdown = llm_result["content_markdown"]

        # Step 6: Validate output length and source coverage. If the model
        # reaches its output limit or stops mid-section, make one grounded
        # revision request before showing the preview to the user.
        quality_report = validate_document_output(doc_markdown, size, retrieved_passages)
        if not quality_report["is_valid"]:
            logger.warning(
                "Initial document failed quality checks; requesting one complete revision: %s",
                quality_report["warnings"],
            )
            revised_result = generate_confluence_document(
                topic=topic,
                passages=retrieved_passages,
                size=size,
                space_key=space,
                previous_draft=doc_markdown,
            )
            revised_markdown = revised_result["content_markdown"]
            revised_quality = validate_document_output(
                revised_markdown, size, retrieved_passages
            )
            # Keep the revision only when it improves the quality report.
            if revised_quality["word_count"] >= quality_report["word_count"] and (
                revised_quality["is_valid"] or not quality_report["is_valid"]
            ):
                llm_result = revised_result
                doc_markdown = revised_markdown
                quality_report = revised_quality

        # Step 7: Return preview payload for user confirmation
        return {
            "success": True,
            "stage": "preview",
            "topic": topic,
            "source_id": source_id,
            "size": size,
            "space": space,
            "parent_page_id": parent_page_id,
            "document_markdown": doc_markdown,
            "quality_report": quality_report,
            "retrieved_passages": retrieved_passages,
            "provider": llm_result.get("provider"),
            "model": llm_result.get("model"),
        }

    def publish_confirmed_document(
        self,
        topic: str,
        document_markdown: str,
        space: str,
        parent_page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes Steps 9 to 11 (after user confirmation):
        Creates Confluence page via MCP -> Retrieves URL -> Indexes final document in OpenSearch.
        """
        # Step 9 & 10: Create Confluence page through Atlassian MCP
        publish_res = self.mcp.create_page(
            title=topic,
            content_markdown=document_markdown,
            space_key=space,
            parent_page_id=parent_page_id,
        )

        page_url = publish_res.get("url")
        page_id = publish_res.get("id")

        # Step 11: Store/index the final document in Amazon OpenSearch
        final_doc_id = self.opensearch.index_final_document(
            title=topic,
            content=document_markdown,
            confluence_page_id=page_id,
            confluence_url=page_url,
            space_key=space,
        )

        return {
            "success": True,
            "page_id": page_id,
            "page_url": page_url,
            "space": space,
            "opensearch_doc_id": final_doc_id,
            "status": "published_and_indexed",
        }

    def create_jira_task(
        self,
        project_key: str,
        summary: str,
        description: str,
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Validate inputs and publish a new Jira issue via Atlassian MCP.
        """
        from validators import validate_jira_input

        errors = validate_jira_input(
            project_key=project_key,
            summary=summary,
            issue_type=issue_type,
            description=description,
        )
        if errors:
            return {
                "success": False,
                "errors": errors,
            }

        res = self.mcp.create_jira_issue(
            project_key=project_key,
            summary=summary,
            description=description,
            issue_type=issue_type,
            priority=priority,
            labels=labels,
        )
        return {
            "success": True,
            "issue": res,
        }


