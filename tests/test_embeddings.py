import sys
import types

import pytest

from shopdesk.rag import embeddings
from shopdesk.rag.embeddings import (EmbeddingsUnavailable, FastEmbedEmbedder, dot, make_embedder, normalize)


# ---------- the vector helpers ----------

def test_normalize_gives_unit_length_and_leaves_zero_alone():
    assert normalize([3.0, 4.0]) == [0.6, 0.8]
    assert normalize([0.0, 0.0]) == [0.0, 0.0]


def test_the_dot_product_of_unit_vectors_is_cosine_similarity():
    assert dot(normalize([1, 0]), normalize([2, 0])) == pytest.approx(1.0)      # same direction
    assert dot(normalize([1, 0]), normalize([0, 5])) == pytest.approx(0.0)      # unrelated
    assert dot(normalize([1, 0]), normalize([-1, 0])) == pytest.approx(-1.0)    # opposite


# ---------- the fastembed adapter, tested against a stand-in library ----------

class FakeTextEmbedding:
    instances = []

    def __init__(self, model_name, cache_dir=None):
        self.model_name, self.cache_dir, self.calls = model_name, cache_dir, []
        FakeTextEmbedding.instances.append(self)

    def passage_embed(self, texts):
        self.calls.append(("passage", list(texts)))
        return iter([[1.0, 0.0] for _ in texts])

    def query_embed(self, query):
        self.calls.append(("query", query))
        return iter([[0.0, 1.0]])


@pytest.fixture
def fake_fastembed(monkeypatch, tmp_path):
    module = types.ModuleType("fastembed")
    module.TextEmbedding = FakeTextEmbedding
    FakeTextEmbedding.instances.clear()
    monkeypatch.setitem(sys.modules, "fastembed", module)
    monkeypatch.setattr(embeddings, "CACHE_DIR", tmp_path / "cache")
    return module


def test_documents_use_passage_embedding_and_questions_use_query_embedding(fake_fastembed):
    embedder = FastEmbedEmbedder("some/model")
    assert embedder.embed_documents(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]
    assert embedder.embed_query("question") == [0.0, 1.0]
    calls = FakeTextEmbedding.instances[0].calls
    assert calls == [("passage", ["a", "b"]), ("query", "question")]


def test_the_model_is_cached_in_the_project_folder(fake_fastembed, tmp_path):
    FastEmbedEmbedder("some/model")
    assert FakeTextEmbedding.instances[0].cache_dir == str(tmp_path / "cache")


def test_a_missing_library_gives_an_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)           # makes 'import fastembed' fail
    with pytest.raises(EmbeddingsUnavailable, match="pip install fastembed"):
        FastEmbedEmbedder()


def test_a_model_that_cannot_load_is_reported_clearly(monkeypatch, tmp_path):
    class Broken:
        def __init__(self, **kwargs):
            raise RuntimeError("no internet")
    module = types.ModuleType("fastembed")
    module.TextEmbedding = Broken
    monkeypatch.setitem(sys.modules, "fastembed", module)
    monkeypatch.setattr(embeddings, "CACHE_DIR", tmp_path / "cache")
    with pytest.raises(EmbeddingsUnavailable, match="could not load"):
        FastEmbedEmbedder("some/model")


def test_make_embedder_understands_its_spec_strings(fake_fastembed):
    assert make_embedder("fastembed").name == embeddings.DEFAULT_MODEL
    assert make_embedder("fastembed:sentence-transformers/all-MiniLM-L6-v2").name == "sentence-transformers/all-MiniLM-L6-v2"
    with pytest.raises(ValueError):
        make_embedder("openai")
