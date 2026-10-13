import pytest

from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import Chunk
from shopdesk.rag.dense import DenseIndex
from shopdesk.rag.hybrid import HybridIndex, reciprocal_rank_fusion

# A pretend "meaning" model: phrases that mean the same thing light up the same dimension.
CONCEPTS = {
    "refund": ["refund", "money back", "return", "reimburse"],
    "time": ["window", "days", "month", "weeks"],
    "shipping": ["ship", "deliver", "package"],
    "warranty": ["warranty", "defect", "covered", "broken"],
}


class ConceptEmbedder:
    name = "concepts"

    def _vector(self, text):
        lower = text.lower()
        return [float(sum(lower.count(phrase) for phrase in phrases)) for phrases in CONCEPTS.values()]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


def chunk(chunk_id, section, text):
    return Chunk(chunk_id, f"{chunk_id}.md", "Policy", section, text)


CHUNKS = [
    chunk("refund#windows", "Windows", "Items can be returned for a refund within 30 days of delivery."),
    chunk("ship#costs", "Costs", "Standard shipping is free over fifty dollars."),
    chunk("warranty#cover", "Cover", "Electronics are covered for twelve months against defects."),
]
VOCABULARY_MISMATCH = "Can I get my money back on something I bought a month ago?"


# ---------- search by meaning ----------

def test_meaning_search_finds_a_chunk_that_shares_no_words_with_the_question():
    dense = DenseIndex(CHUNKS, ConceptEmbedder())
    assert dense.search(VOCABULARY_MISMATCH, k=3)[0].chunk.id == "refund#windows"


def test_dense_search_always_returns_k_results_even_for_nonsense():
    dense = DenseIndex(CHUNKS, ConceptEmbedder())
    assert len(dense.search("zzz qqq", k=3)) == 3


def test_dense_results_are_best_first_and_deterministic():
    scores = [r.score for r in DenseIndex(CHUNKS, ConceptEmbedder()).search("refund within days", k=3)]
    assert scores == sorted(scores, reverse=True)


# ---------- merging two rankings ----------

def test_reciprocal_rank_fusion_adds_one_over_k_plus_rank_from_every_list():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_an_item_both_searches_like_beats_an_item_only_one_ranks_first():
    fused = reciprocal_rank_fusion([["x", "y"], ["y", "z"]])
    assert [item for item, _ in fused][0] == "y"


def test_ties_are_broken_the_same_way_every_time():
    ids = [item for item, _ in reciprocal_rank_fusion([["a", "b"], ["b", "a"]])]
    assert ids == ["a", "b"]


def test_fusion_needs_no_score_scales():
    # only ranks are used, so wildly different score ranges cannot dominate
    assert reciprocal_rank_fusion([["a"], ["b"]]) == reciprocal_rank_fusion([["a"], ["b"]])


# ---------- hybrid ----------

def test_hybrid_rescues_a_question_keyword_search_cannot_answer():
    bm25 = BM25Index(CHUNKS)
    assert "refund#windows" not in [r.chunk.id for r in bm25.search(VOCABULARY_MISMATCH, k=3)]   # keywords miss it
    hybrid = HybridIndex(bm25, DenseIndex(CHUNKS, ConceptEmbedder()))
    assert "refund#windows" in [r.chunk.id for r in hybrid.search(VOCABULARY_MISMATCH, k=3)]


def test_hybrid_keeps_what_keyword_search_does_well():
    bm25 = BM25Index(CHUNKS)
    hybrid = HybridIndex(bm25, DenseIndex(CHUNKS, ConceptEmbedder()))
    assert hybrid.search("standard shipping", k=3)[0].chunk.id == "ship#costs"


def test_hybrid_respects_k_and_never_repeats_a_chunk():
    hybrid = HybridIndex(BM25Index(CHUNKS), DenseIndex(CHUNKS, ConceptEmbedder()))
    ids = [r.chunk.id for r in hybrid.search("refund warranty shipping", k=2)]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_the_search_names_itself_for_the_traces():
    dense = DenseIndex(CHUNKS, ConceptEmbedder())
    assert dense.name == "dense:concepts"
    assert HybridIndex(BM25Index(CHUNKS), dense).name == "hybrid:concepts"
    assert BM25Index(CHUNKS).name == "bm25"
