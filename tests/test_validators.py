"""
tests/test_validators.py — Unit tests for input and output validation.
"""

import pytest
from validators import count_words, validate_document_output, validate_input


def test_validate_input_valid():
    errors = validate_input(
        topic="Cloud Architecture Guidelines",
        source_content="This is a sufficiently long source content body that contains multiple sentences to describe technical details and prevent hallucinations completely.",
        size="medium",
        space="TECH",
    )
    assert errors == []


def test_validate_input_empty_topic():
    errors = validate_input(
        topic="",
        source_content="Some long enough content text for the validator to accept without issue.",
        size="medium",
        space="TECH",
    )
    assert any("topic/title cannot be empty" in err for err in errors)


def test_validate_input_sparse_source():
    errors = validate_input(
        topic="Cloud Architecture",
        source_content="Too short.",
        size="medium",
        space="TECH",
    )
    assert any("too sparse" in err for err in errors)


def test_validate_input_invalid_size():
    errors = validate_input(
        topic="Cloud Architecture",
        source_content="Some long enough content text for the validator to accept without issue.",
        size="extra-huge",
        space="TECH",
    )
    assert any("Invalid document size" in err for err in errors)


def test_count_words():
    text = "# Title\n\nThis is **four** words."
    assert count_words(text) == 5


def test_validate_document_output_citations_detected():
    sample_doc = "This architecture is resilient [Source 1]. Financial records are retained for 7 years [Source 2]."
    report = validate_document_output(sample_doc, size="short", retrieved_sources=[{"id": 1}, {"id": 2}])
    assert report["has_citations"] is True
    assert report["citation_count"] == 2


def test_validate_document_output_missing_citations():
    sample_doc = "This is a document that completely omits references."
    report = validate_document_output(sample_doc, size="short", retrieved_sources=[{"id": 1}])
    assert report["has_citations"] is False
    assert any("does not include explicit inline source citations" in w for w in report["warnings"])

