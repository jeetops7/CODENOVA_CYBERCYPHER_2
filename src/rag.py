"""
LogiFlow Sentinel - policy retrieval (RAG).

Rules in ``data/knowledge_base.txt`` become LangChain ``Document``s, are
embedded locally (FastEmbed, BAAI/bge-small, no API key) and stored in a FAISS
vector store that is persisted under ``.cache/``. If the embedding model cannot
be loaded (e.g. offline first run) retrieval falls back to an in-memory TF-IDF
index so the app still works. Every hit reports which backend served it.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parent.parent
KB_FILE = ROOT / "data" / "knowledge_base.txt"

CACHE_DIR = ROOT / ".cache" / "faiss"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
_RULE_LINE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "for", "from", "if",
    "in", "is", "it", "of", "on", "or", "must", "than", "the", "to", "with",
    "all", "any", "not", "that", "their", "this", "which",
}


@dataclass
class Hit:
    rule_id: str
    text: str
    score: float
    backend: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_rules(path: Path = KB_FILE) -> List[Dict[str, str]]:
    """Parse the numbered rule list into ``{"id": "R4", "text": ...}`` records."""
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _RULE_LINE.match(line)
        if match:
            rules.append({"id": f"R{match.group(1)}", "text": match.group(2)})
    return rules


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w.rstrip("s") for w in words if w not in _STOPWORDS and len(w) > 1]


class LocalIndex:
    """Dependency-free TF-IDF cosine search, used when the embedding model is unavailable."""

    name = "local-tfidf"

    def __init__(self, rules: List[Dict[str, str]]) -> None:
        self._rules = rules
        docs = [Counter(_tokens(r["text"])) for r in rules]
        df = Counter(t for d in docs for t in d)
        n = len(docs)
        self._idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self._vecs = [self._weigh(d) for d in docs]

    def _weigh(self, counts: Counter) -> Dict[str, float]:
        vec = {t: c * self._idf.get(t, 0.0) for t, c in counts.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str, top_k: int) -> List[Hit]:
        q = self._weigh(Counter(_tokens(query)))
        scored = [
            Hit(r["id"], r["text"], sum(w * v.get(t, 0.0) for t, w in q.items()), self.name)
            for r, v in zip(self._rules, self._vecs)
        ]
        scored = [h for h in scored if h.score > 0]
        return sorted(scored, key=lambda h: h.score, reverse=True)[:top_k]


class FaissIndex:
    """LangChain FAISS vector store over locally computed embeddings."""

    name = "faiss"

    def __init__(self, rules: List[Dict[str, str]]) -> None:
        from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
        from langchain_community.vectorstores import FAISS

        embeddings = FastEmbedEmbeddings(model_name=EMBED_MODEL)
        stamp = CACHE_DIR / "rules.stamp"
        fingerprint = hashlib.md5("\n".join(r["text"] for r in rules).encode()).hexdigest() + EMBED_MODEL
        if (CACHE_DIR / "index.faiss").exists() and stamp.exists() and stamp.read_text() == fingerprint:
            self._store = FAISS.load_local(str(CACHE_DIR), embeddings, allow_dangerous_deserialization=True)
        else:
            docs = [Document(page_content=r["text"], metadata={"rule_id": r["id"]}) for r in rules]
            self._store = FAISS.from_documents(docs, embeddings)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._store.save_local(str(CACHE_DIR))
            stamp.write_text(fingerprint)

    def search(self, query: str, top_k: int) -> List[Hit]:
        results = self._store.similarity_search_with_score(query, k=top_k)
        # embeddings are unit-norm, so cosine similarity = 1 - L2^2 / 2
        return [Hit(d.metadata["rule_id"], d.page_content, round(1 - float(dist) ** 2 / 2, 3), self.name)
                for d, dist in results]


class KnowledgeBase:
    """Single entry point for policy retrieval with automatic fallback."""

    def __init__(self, force_local: bool = False) -> None:
        self.rules = load_rules()
        self._by_id = {r["id"]: r["text"] for r in self.rules}
        self._index = LocalIndex(self.rules)
        self.error: Optional[str] = None
        if not force_local:
            try:
                self._index = FaissIndex(self.rules)
            except Exception as exc:  # model download failed, faiss missing...
                self.error = f"{type(exc).__name__}: {exc}"

    @property
    def backend(self) -> str:
        return self._index.name

    def get(self, rule_id: str) -> Optional[str]:
        return self._by_id.get(rule_id)

    def retrieve(self, query: str, top_k: int = 4) -> List[Hit]:
        return self._index.search(query, top_k)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build / query the policy index.")
    parser.add_argument("--query", help="Run a test query against the index")
    args = parser.parse_args()
    kb = KnowledgeBase()
    print(f"backend={kb.backend} rules={len(kb.rules)}" + (f" error={kb.error}" if kb.error else ""))
    if args.query:
        for h in kb.retrieve(args.query):
            print(f"{h.score:.3f}  {h.rule_id}  {h.text}")
