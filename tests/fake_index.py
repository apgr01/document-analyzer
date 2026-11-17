"""Indice vettoriale finto per i test della modalità RAG: in memoria, con una "somiglianza"
semplice (parole in comune), così i test non dipendono da ChromaDB né da modelli scaricati."""

from __future__ import annotations

import re
from typing import Any


def words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class FakeIndex:
    def __init__(self):
        self.items: dict[str, tuple[str, dict[str, Any]]] = {}
        self.queries: list[tuple[str, int, dict | None]] = []

    def upsert(self, ids, documents, metadatas):
        for i, doc, meta in zip(ids, documents, metadatas, strict=True):
            self.items[i] = (doc, meta)

    def query(self, text, n_results, where=None):
        self.queries.append((text, n_results, where))
        found = [(doc, meta) for doc, meta in self.items.values()
                 if not where or all(meta.get(k) == v for k, v in where.items())]
        found.sort(key=lambda x: -len(words(x[0]) & words(text)))
        return [{"text": doc, "metadata": meta, "distance": 1.0 / (1 + len(words(doc) & words(text)))}
                for doc, meta in found[:n_results]]

    def count(self):
        return len(self.items)
