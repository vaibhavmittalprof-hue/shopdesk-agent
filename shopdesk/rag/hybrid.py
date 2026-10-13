from shopdesk.rag.bm25 import SearchResult


def reciprocal_rank_fusion(rankings, k: int = 60):
    """
    Merge several ranked lists into one. Each item earns 1 / (k + rank) from every list it appears in,
    so items that are ranked well by MORE than one search float to the top. It uses ranks, not scores,
    so it needs no tuning of weights and no score normalization (BM25 scores and cosine similarities
    live on completely different scales).

    rankings: a list of lists of ids, each best first.   Returns [(id, score)], best first.
    """
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


class HybridIndex:
    """Keyword search (BM25) and meaning search (dense), merged with reciprocal rank fusion."""

    def __init__(self, sparse, dense, candidates: int = 10, rrf_k: int = 60):
        self.sparse, self.dense = sparse, dense
        self.candidates, self.rrf_k = candidates, rrf_k
        self.name = f"hybrid:{dense.embedder.name}"

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        sparse_hits = self.sparse.search(query, self.candidates)
        dense_hits = self.dense.search(query, self.candidates)
        chunks = {r.chunk.id: r.chunk for r in sparse_hits + dense_hits}
        fused = reciprocal_rank_fusion(
            [[r.chunk.id for r in sparse_hits], [r.chunk.id for r in dense_hits]], self.rrf_k)
        return [SearchResult(chunks[chunk_id], score) for chunk_id, score in fused[:k]]