"""Incident knowledge base (the RAG layer in the design flow).

`KnowledgeBase` is the port. The prototype uses a dependency-free TF-IDF
retriever; production would swap in embeddings in pgvector (or any vector
store) behind the same interface.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from batchiq.domain.models import Incident

_TOKEN = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 2]


class KnowledgeBase(Protocol):
    def search(self, query: str, k: int = 3) -> list[tuple[Incident, float]]: ...
    def add(self, incident: Incident) -> None: ...


class TfidfKnowledgeBase:
    def __init__(self, incidents: list[Incident]) -> None:
        self.docs: list[Incident] = []
        self.vecs: list[dict[str, float]] = []
        self.df: Counter = Counter()
        for i in incidents:
            self.add(i)

    @staticmethod
    def _text(i: Incident) -> str:
        # Job ids are repeated so that "same job" dominates similarity.
        jobs = " ".join(j.split("::")[-1].replace("/", " ").replace(".", " ") for j in i.jobs)
        return f"{i.title} {i.symptoms} {i.root_cause} {i.error_code or ''} {jobs} {jobs} {i.scheduler.value}"

    def add(self, incident: Incident) -> None:
        self.docs.append(incident)
        toks = _tokens(self._text(incident))
        self.df.update(set(toks))
        self._reindex()

    def _reindex(self) -> None:
        n = len(self.docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in self.df.items()}
        self.vecs = [self._vec(_tokens(self._text(d))) for d in self.docs]

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        v = {t: c * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def search(self, query: str, k: int = 3) -> list[tuple[Incident, float]]:
        q = self._vec(_tokens(query))
        scored = [(d, sum(q.get(t, 0) * w for t, w in v.items())) for d, v in zip(self.docs, self.vecs)]
        scored = [s for s in scored if s[1] > 0.05]
        return sorted(scored, key=lambda s: -s[1])[:k]
