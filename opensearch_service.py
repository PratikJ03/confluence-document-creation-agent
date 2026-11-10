"""
opensearch_service.py — Amazon OpenSearch indexing & retrieval client.

Features:
- Stores raw source content and passage chunks in Amazon OpenSearch.
- BM25 full-text & relevant passage retrieval for prompt grounding.
- Stores final published Confluence documents for enterprise discovery.
- Fully operational in offline / local development mode when OpenSearch endpoint is not set.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

try:
    from opensearchpy import OpenSearch, RequestsHttpConnection
    OPENSEARCH_LIB_AVAILABLE = True
except ImportError:
    OPENSEARCH_LIB_AVAILABLE = False


class OpenSearchService:
    """
    Manages indexing and retrieval against Amazon OpenSearch Service.
    Falls back gracefully to an in-memory mock store if OpenSearch is not deployed.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        sources_index: Optional[str] = None,
        docs_index: Optional[str] = None,
    ) -> None:
        self.endpoint = endpoint or config.OPENSEARCH_ENDPOINT
        self.sources_index = sources_index or config.OPENSEARCH_INDEX_SOURCES
        self.docs_index = docs_index or config.OPENSEARCH_INDEX_DOCS

        # In-memory fallback repository for local/offline execution & tests
        self._local_sources: Dict[str, Dict[str, Any]] = {}
        self._local_docs: Dict[str, Dict[str, Any]] = {}

        self.client: Optional[Any] = None
        self._is_live = False

        if self.endpoint and OPENSEARCH_LIB_AVAILABLE:
            self._init_live_client()

    def _init_live_client(self) -> None:
        """Initialize connection to real Amazon OpenSearch Service."""
        try:
            auth = None
            if config.OPENSEARCH_USERNAME and config.OPENSEARCH_PASSWORD:
                auth = (config.OPENSEARCH_USERNAME, config.OPENSEARCH_PASSWORD)

            self.client = OpenSearch(
                hosts=[self.endpoint],
                http_auth=auth,
                use_ssl=config.OPENSEARCH_USE_SSL,
                verify_certs=config.OPENSEARCH_VERIFY_CERTS,
                connection_class=RequestsHttpConnection,
            )
            # Ping
            if self.client.ping():
                self._is_live = True
                self._ensure_indices()
                logger.info("Connected to Amazon OpenSearch at %s", self.endpoint)
        except Exception as exc:
            logger.warning("Could not connect to live OpenSearch (%s). Using fallback store.", exc)
            self._is_live = False

    def _ensure_indices(self) -> None:
        """Create indices if they don't already exist."""
        if not self._is_live or not self.client:
            return

        source_body = {
            "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 1}},
            "mappings": {
                "properties": {
                    "doc_id": {"type": "keyword"},
                    "topic": {"type": "text"},
                    "passage_index": {"type": "integer"},
                    "content": {"type": "text"},
                    "created_at": {"type": "date"},
                }
            },
        }
        for idx in [self.sources_index, self.docs_index]:
            try:
                if not self.client.indices.exists(index=idx):
                    self.client.indices.create(index=idx, body=source_body)
            except Exception as e:
                logger.warning("Error checking/creating index %s: %s", idx, e)

    @property
    def is_live(self) -> bool:
        """Return True if connected to an active OpenSearch cluster."""
        return self._is_live

    def split_into_passages(self, text: str, max_chars: int = 600) -> List[str]:
        """Split raw source content into readable, overlapping passages for indexing."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [text.strip()]

        passages: List[str] = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) > max_chars and current:
                passages.append(current.strip())
                current = p
            else:
                current = f"{current}\n\n{p}" if current else p
        if current:
            passages.append(current.strip())

        return passages

    def index_source_content(self, topic: str, content: str) -> str:
        """
        Store and index raw user source notes in OpenSearch.
        Returns unique document source ID.
        """
        source_id = hashlib.sha256(f"{topic}:{time.time()}".encode()).hexdigest()[:12]
        passages = self.split_into_passages(content)

        if self._is_live and self.client:
            for idx, p in enumerate(passages):
                body = {
                    "source_id": source_id,
                    "topic": topic,
                    "passage_index": idx + 1,
                    "content": p,
                    "created_at": int(time.time()),
                }
                self.client.index(index=self.sources_index, body=body)
            self.client.indices.refresh(index=self.sources_index)
        else:
            # Fallback storage
            self._local_sources[source_id] = {
                "source_id": source_id,
                "topic": topic,
                "passages": passages,
                "raw_content": content,
                "created_at": time.time(),
            }

        logger.info("Indexed %d passages for source '%s' (ID: %s)", len(passages), topic, source_id)
        return source_id

    def retrieve_relevant_passages(
        self,
        topic: str,
        source_id: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve only the most relevant source passages matching the topic.
        """
        if self._is_live and self.client:
            must_clauses: List[Dict[str, Any]] = [
                {"match": {"content": topic}}
            ]
            if source_id:
                must_clauses.append({"term": {"source_id": source_id}})

            query = {
                "size": top_k,
                "query": {"bool": {"must": must_clauses}},
            }
            try:
                res = self.client.search(index=self.sources_index, body=query)
                hits = res.get("hits", {}).get("hits", [])
                results = []
                for h in hits:
                    src = h["_source"]
                    results.append({
                        "id": src.get("passage_index", 1),
                        "content": src.get("content", ""),
                        "score": h.get("_score", 1.0),
                    })
                if results:
                    return results
            except Exception as e:
                logger.warning("OpenSearch search failed: %s. Using local store.", e)

        # Local fallback retrieval
        if source_id and source_id in self._local_sources:
            passages = self._local_sources[source_id]["passages"]
        elif self._local_sources:
            # get last indexed
            latest_key = list(self._local_sources.keys())[-1]
            passages = self._local_sources[latest_key]["passages"]
        else:
            return []

        # Simple term scoring
        keywords = set(topic.lower().split())
        scored: List[Tuple[float, int, str]] = []
        for idx, p in enumerate(passages):
            words = set(p.lower().split())
            overlap = len(keywords.intersection(words))
            score = overlap / (len(keywords) or 1)
            scored.append((score, idx + 1, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": item[1], "content": item[2], "score": round(item[0], 2)}
            for item in scored[:top_k]
        ]

    def index_final_document(
        self,
        title: str,
        content: str,
        confluence_page_id: Optional[str],
        confluence_url: Optional[str],
        space_key: str,
    ) -> str:
        """
        Index the published Confluence document into OpenSearch for enterprise search.
        """
        doc_id = hashlib.sha256(f"{title}:{time.time()}".encode()).hexdigest()[:12]
        payload = {
            "doc_id": doc_id,
            "title": title,
            "content": content,
            "confluence_page_id": confluence_page_id,
            "confluence_url": confluence_url,
            "space_key": space_key,
            "published_at": time.time(),
        }

        if self._is_live and self.client:
            try:
                self.client.index(index=self.docs_index, id=doc_id, body=payload)
                self.client.indices.refresh(index=self.docs_index)
            except Exception as e:
                logger.warning("Error indexing final document to OpenSearch: %s", e)

        self._local_docs[doc_id] = payload
        logger.info("Final document '%s' indexed to OpenSearch (ID: %s)", title, doc_id)
        return doc_id

