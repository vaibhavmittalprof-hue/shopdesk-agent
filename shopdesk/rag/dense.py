from shopdesk.rag.bm25 import SearchResult
from shopdesk.rag.embeddings import Embedder, dot, normalize


class DenseIndex:
    """
    Search by MEANING. Every chunk becomes a vector; so does the question. The chunks whose vectors
    point the same way as the question's (highest cosine similarity) are the best matches.
    Unlike BM25 it needs no shared words ("money back" can match "refund"), but it always returns
    the k nearest chunks, even when none of them is relevant.
    """

    def __init__(self, chunks, embedder: Embedder):
        self.chunks = list(chunks)
        self.embedder = embedder
        self.name = f"dense:{embedder.name}"
        vectors = embedder.embed_documents([c.search_text for c in self.chunks])
        self.vectors = [normalize(v) for v in vectors]      # unit length, so a dot product IS cosine similarity

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        q = normalize(self.embedder.embed_query(query))
        scored = [(dot(q, v), i) for i, v in enumerate(self.vectors)]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [SearchResult(self.chunks[i], score) for score, i in scored[:k]]