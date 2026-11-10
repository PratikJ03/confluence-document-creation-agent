"""
validators.py — Input validation, document size constraints, and citation checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class DocumentSizeConfig:
    label: str
    min_words: int
    max_words: int
    description: str


DOCUMENT_SIZES: Dict[str, DocumentSizeConfig] = {
    "short": DocumentSizeConfig("short", 300, 500, "Short summary / memo (300–500 words)"),
    "medium": DocumentSizeConfig("medium", 800, 1200, "Standard Confluence doc / guide (800–1,200 words)"),
    "long": DocumentSizeConfig("long", 1500, 2000, "Detailed architecture / specification (1,500–2,000 words)"),
}


def validate_input(
    topic: str,
    source_content: str,
    size: str,
    space: str,
) -> List[str]:
    """
    Validate all user inputs before processing or indexing.
    Returns a list of error strings (empty if valid).
    """
    errors: List[str] = []

    if not topic or not topic.strip():
        errors.append("Document topic/title cannot be empty.")
    elif len(topic.strip()) < 3:
        errors.append("Topic/title must be at least 3 characters long.")
    elif len(topic.strip()) > 255:
        errors.append("Topic/title cannot exceed 255 characters.")

    if not source_content or not source_content.strip():
        errors.append("Source content / reference notes cannot be empty.")
    else:
        word_count = len(source_content.strip().split())
        if word_count < 20:
            errors.append(
                f"Source content is too sparse ({word_count} words). Provide at least 20 words of source material to avoid hallucinations."
            )

    if size.lower() not in DOCUMENT_SIZES:
        valid_sizes = ", ".join(DOCUMENT_SIZES.keys())
        errors.append(f"Invalid document size '{size}'. Choose from: {valid_sizes}.")

    if not space or not space.strip():
        errors.append("Target Confluence space key or space ID is required.")

    return errors


def count_words(text: str) -> int:
    """Return word count of raw text or markdown (stripping code/html tags)."""
    clean_text = re.sub(r"<[^>]+>", " ", text)
    clean_text = re.sub(r"[#*_`~>\[\]\(\)\-\+]", " ", clean_text)
    words = clean_text.split()
    return len(words)


def validate_document_output(
    document_text: str,
    size: str,
    retrieved_sources: List[Dict[str, str]],
) -> Dict[str, any]:
    """
    Validate generated document length and verify that it contains source citations.
    """
    size_cfg = DOCUMENT_SIZES.get(size.lower(), DOCUMENT_SIZES["medium"])
    words = count_words(document_text)

    # Allow a small 15% tolerance on boundaries
    min_acceptable = int(size_cfg.min_words * 0.85)
    max_acceptable = int(size_cfg.max_words * 1.15)

    within_bounds = min_acceptable <= words <= max_acceptable
    stripped_text = document_text.rstrip()
    has_complete_ending = bool(stripped_text) and stripped_text[-1] in ".!?)]}"

    # Citation check: looks for [Source X] or parenthetical references
    citation_patterns = [
        r"\[Source\s*\d+\]",
        r"\[Passage\s*\d+\]",
        r"\(Source\s*\d+\)",
        r"\(Passage\s*\d+\)",
        r"\[Ref\s*\d+\]",
    ]
    citations_found = []
    for pat in citation_patterns:
        matches = re.findall(pat, document_text, re.IGNORECASE)
        citations_found.extend(matches)

    has_citations = len(citations_found) > 0

    warnings: List[str] = []
    if not within_bounds:
        if words < min_acceptable:
            warnings.append(
                f"Word count ({words} words) is below the requested target of {size_cfg.min_words}–{size_cfg.max_words} words."
            )
        else:
            warnings.append(
                f"Word count ({words} words) exceeds the requested target of {size_cfg.min_words}–{size_cfg.max_words} words."
            )

    if not has_citations and len(retrieved_sources) > 0:
        warnings.append(
            "The generated document does not include explicit inline source citations ([Source X])."
        )

    if not has_complete_ending:
        warnings.append(
            "The generated document appears incomplete because it does not end with a complete sentence or citation."
        )

    return {
        "word_count": words,
        "target_range": f"{size_cfg.min_words}–{size_cfg.max_words}",
        "within_bounds": within_bounds,
        "has_citations": has_citations,
        "has_complete_ending": has_complete_ending,
        "citation_count": len(citations_found),
        "warnings": warnings,
        "is_valid": len(warnings) == 0,
    }

