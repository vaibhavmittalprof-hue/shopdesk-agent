import os
import sys

from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import load_policy_chunks
from shopdesk.rag.dense import DenseIndex
from shopdesk.rag.embeddings import EmbeddingsUnavailable, make_embedder
from shopdesk.rag.hybrid import HybridIndex


def build_policy_index(mode=None, embedder=None):
    """
    Which search the agent uses, chosen by the POLICY_SEARCH setting:
        bm25    keyword search only (the default, nothing extra to install)
        dense   search by meaning only
        hybrid  both, merged (needs the embeddings library)
    If embeddings are requested but unavailable, we warn and fall back to BM25, never crash.
    """
    mode = (mode or os.getenv("POLICY_SEARCH", "bm25")).strip().lower()
    if mode not in ("bm25", "dense", "hybrid"):
        raise ValueError(f"POLICY_SEARCH must be bm25, dense or hybrid, not '{mode}'")

    chunks = load_policy_chunks()
    bm25 = BM25Index(chunks)
    if mode == "bm25":
        return bm25

    try:
        embedder = embedder or make_embedder(os.getenv("EMBEDDING_BACKEND", "fastembed"))
    except EmbeddingsUnavailable as exc:
        print(f"[warning] POLICY_SEARCH={mode} needs embeddings, but they are unavailable ({exc}). "
              f"Using BM25 only.", file=sys.stderr)
        return bm25

    dense = DenseIndex(chunks, embedder)
    return dense if mode == "dense" else HybridIndex(bm25, dense)