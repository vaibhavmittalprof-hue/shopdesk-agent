import pytest

from shopdesk.rag import factory
from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.dense import DenseIndex
from shopdesk.rag.embeddings import EmbeddingsUnavailable
from shopdesk.rag.hybrid import HybridIndex
from tests.test_dense_hybrid import ConceptEmbedder


def test_the_default_is_keyword_search_and_needs_nothing_extra(monkeypatch):
    monkeypatch.delenv("POLICY_SEARCH", raising=False)
    assert isinstance(factory.build_policy_index(), BM25Index)


def test_the_setting_chooses_the_search(monkeypatch):
    monkeypatch.setenv("POLICY_SEARCH", "hybrid")
    assert isinstance(factory.build_policy_index(embedder=ConceptEmbedder()), HybridIndex)
    monkeypatch.setenv("POLICY_SEARCH", "dense")
    assert isinstance(factory.build_policy_index(embedder=ConceptEmbedder()), DenseIndex)


def test_an_explicit_argument_beats_the_setting(monkeypatch):
    monkeypatch.setenv("POLICY_SEARCH", "dense")
    assert isinstance(factory.build_policy_index("bm25"), BM25Index)


def test_an_unknown_setting_is_an_error():
    with pytest.raises(ValueError, match="POLICY_SEARCH"):
        factory.build_policy_index("magic")


def test_missing_embeddings_fall_back_to_keyword_search_with_a_warning(monkeypatch, capsys):
    def unavailable(spec):
        raise EmbeddingsUnavailable("fastembed is not installed")
    monkeypatch.setattr(factory, "make_embedder", unavailable)
    index = factory.build_policy_index("hybrid")
    assert isinstance(index, BM25Index)
    assert "Using BM25 only" in capsys.readouterr().err
