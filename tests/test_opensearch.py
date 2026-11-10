"""
tests/test_opensearch.py — Tests for OpenSearch indexing and retrieval.
"""

from opensearch_service import OpenSearchService


def test_opensearch_service_local_fallback():
    svc = OpenSearchService()
    # In absence of a live cluster, is_live is False and local store works
    assert svc.is_live is False

    topic = "AWS Data Retention Policy"
    content = "Passage 1: Financial records are kept 7 years.\n\nPassage 2: Logs are kept 90 days."

    source_id = svc.index_source_content(topic, content)
    assert source_id is not None
    assert len(source_id) > 0

    results = svc.retrieve_relevant_passages("Financial records", source_id=source_id, top_k=2)
    assert len(results) > 0
    assert any("7 years" in r["content"] for r in results)


def test_opensearch_index_final_document():
    svc = OpenSearchService()
    doc_id = svc.index_final_document(
        title="Architecture Guide",
        content="# Guide Content",
        confluence_page_id="12345",
        confluence_url="https://wiki.atlassian.net/pages/12345",
        space_key="TECH",
    )
    assert doc_id is not None
    assert doc_id in svc._local_docs
    assert svc._local_docs[doc_id]["confluence_page_id"] == "12345"

