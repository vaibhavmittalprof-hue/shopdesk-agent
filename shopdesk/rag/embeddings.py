import math
from pathlib import Path
from typing import Protocol, Sequence

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"      # small (about 67 MB), runs on a normal laptop CPU
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "fastembed"


class EmbeddingsUnavailable(RuntimeError):
    """Raised when the embedding library or model cannot be used. The message says how to fix it."""


class Embedder(Protocol):
    """Anything that can turn text into numbers (a 'vector') that capture its meaning."""
    name: str

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Embeddings from the 'fastembed' library: small models, no PyTorch needed."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingsUnavailable("fastembed is not installed. Run:  pip install fastembed") from exc
        self.name = model_name
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(model_name=model_name, cache_dir=str(CACHE_DIR))
        except Exception as exc:                  # no internet for the first download, unknown model, ...
            raise EmbeddingsUnavailable(f"could not load the embedding model '{model_name}': {exc}") from exc

    def embed_documents(self, texts):
        return [[float(x) for x in vector] for vector in self._model.passage_embed(list(texts))]

    def embed_query(self, text):
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


def make_embedder(spec: str) -> Embedder:
    """'fastembed' or 'fastembed:<model name>'."""
    backend, _, model = spec.partition(":")
    if backend == "fastembed":
        return FastEmbedEmbedder(model or DEFAULT_MODEL)
    raise ValueError(f"unknown embedding backend '{spec}' (use 'fastembed' or 'fastembed:<model>')")


# ---------- small vector helpers (plain Python: our corpus has only a few dozen chunks) ----------

def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def normalize(vector: Sequence[float]) -> list[float]:
    length = math.sqrt(dot(vector, vector))
    return [x / length for x in vector] if length else list(vector)