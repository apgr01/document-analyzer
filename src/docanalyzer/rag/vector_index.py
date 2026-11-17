"""Indice vettoriale (ChromaDB) della modalità RAG.

Ogni pagina descritta diventa un elemento dell'indice con id ``<id documento>:<numero
pagina>``. Si usa ``upsert``: se una pagina viene descritta di nuovo, la nuova descrizione
sostituisce quella vecchia.

L'embedding è quello predefinito di ChromaDB, a meno di passarne un altro
(``embedding_function``): così i test girano senza scaricare modelli, e un modello
multilingue locale si potrà aggiungere senza toccare il resto (vedi la roadmap).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RagNotInstalledError(ImportError):
    pass


class VectorIndex:
    def __init__(self, path: Path, collection_name: str, embedding_function: Any = None):
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as e:
            raise RagNotInstalledError(
                "La modalità RAG richiede ChromaDB, che non è installato.\n"
                'Installalo con:  pip install -e ".[rag]"'
            ) from e

        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(path), settings=Settings(allow_reset=True, anonymized_telemetry=False)
        )
        self.collection_name = collection_name
        options = {"embedding_function": embedding_function} if embedding_function is not None else {}
        self.collection = self.client.get_or_create_collection(name=collection_name, **options)

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]) -> None:
        if ids:
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def delete_document(self, doc_id: str) -> None:
        self.collection.delete(where={"doc_id": doc_id})

    def query(self, text: str, n_results: int, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.count() == 0:
            return []
        res = self.collection.query(query_texts=[text], n_results=min(n_results, self.count()), where=where)
        hits = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True):
            hits.append({"text": doc, "metadata": meta, "distance": dist})
        return hits

    def count(self) -> int:
        return self.collection.count()
