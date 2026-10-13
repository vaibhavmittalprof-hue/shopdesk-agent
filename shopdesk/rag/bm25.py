import math
import re
from collections import Counter
from dataclasses import dataclass

from shopdesk.rag.chunking import Chunk

# Very common words that say nothing about the topic. (Negations like "not" are kept on purpose.)
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "it",
    "this", "that", "with", "as", "at", "by", "i", "my", "me", "we", "you", "your", "do", "does",
    "can", "will", "if", "what", "how", "when", "which", "who", "get", "have", "has", "there",
}


def stem_word(word: str) -> str:
    """A tiny stemmer: 'refunded', 'refunds', 'refunding' all become 'refund'."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "ls":   # 'shipp' -> 'ship'
        word = word[:-1]
    return word


def tokenize(text: str, stem: bool = True, drop_stopwords: bool = True) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if drop_stopwords:
        words = [w for w in words if w not in STOPWORDS]
    if stem:
        words = [stem_word(w) for w in words]
    return words


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


class BM25Index:
    """
    BM25: the classic keyword search. A chunk scores higher when it contains the query's words,
    especially RARE words (idf), with diminishing returns for repeats (k1) and a fairness
    adjustment for long chunks (b).
    """

    def __init__(self, chunks, k1: float = 1.5, b: float = 0.75, stem: bool = True,
                 drop_stopwords: bool = True):
        self.chunks = list(chunks)
        self.name = "bm25"
        self.k1, self.b = k1, b
        self.stem, self.drop_stopwords = stem, drop_stopwords

        self.term_counts = [Counter(self._tokens(c.search_text)) for c in self.chunks]
        self.lengths = [sum(counts.values()) for counts in self.term_counts]
        self.avg_length = sum(self.lengths) / len(self.lengths)

        document_frequency = Counter()                     # in how many chunks does each word appear?
        for counts in self.term_counts:
            document_frequency.update(counts.keys())
        n = len(self.chunks)
        self.idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5))
                    for term, df in document_frequency.items()}

    def _tokens(self, text):
        return tokenize(text, self.stem, self.drop_stopwords)

    def score(self, query_terms, index: int) -> float:
        counts, length = self.term_counts[index], self.lengths[index]
        total = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf == 0:
                continue
            norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_length)
            total += self.idf[term] * tf * (self.k1 + 1) / norm
        return total

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        terms = self._tokens(query)
        scored = [(self.score(terms, i), i) for i in range(len(self.chunks))]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))          # best first; ties keep file order
        return [SearchResult(self.chunks[i], s) for s, i in scored[:k] if s > 0]