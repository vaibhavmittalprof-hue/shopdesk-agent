from shopdesk.rag.bm25 import BM25Index, stem_word, tokenize
from shopdesk.rag.chunking import Chunk


def chunk(chunk_id, text, section="Section", title="Title"):
    return Chunk(chunk_id, f"{chunk_id}.md", title, section, text)


# ---------- words ----------

def test_the_stemmer_joins_word_forms():
    assert {stem_word(w) for w in ("refund", "refunds", "refunded", "refunding")} == {"refund"}
    assert {stem_word(w) for w in ("ship", "ships", "shipped", "shipping")} == {"ship"}


def test_short_words_are_left_alone():
    assert stem_word("is") == "is" and stem_word("bus") == "bus" and stem_word("sing") == "sing"


def test_tokenize_lowercases_drops_stop_words_and_keeps_numbers_and_negations():
    words = tokenize("The refund of $200.00 is NOT allowed")
    assert "the" not in words and "of" not in words
    assert "not" in words and "200" in words and "refund" in words


def test_tokenize_can_leave_words_exactly_as_written():
    assert tokenize("The Refunds", stem=False, drop_stopwords=False) == ["the", "refunds"]


# ---------- ranking ----------

def test_the_chunk_with_the_query_word_comes_first():
    index = BM25Index([chunk("a", "apples and oranges"), chunk("b", "bananas and grapes")])
    results = index.search("bananas")
    assert [r.chunk.id for r in results] == ["b"]


def test_chunks_with_no_matching_word_are_not_returned():
    index = BM25Index([chunk("a", "apples"), chunk("b", "bananas")])
    assert index.search("zebra") == []


def test_a_rare_word_counts_more_than_a_common_one():
    chunks = [chunk("common_hit", "delivery policy"), chunk("rare_hit", "zeppelin policy"),
              chunk("x", "delivery rules"), chunk("y", "delivery notes"), chunk("z", "delivery costs")]
    results = BM25Index(chunks).search("delivery zeppelin")
    assert results[0].chunk.id == "rare_hit"          # 'zeppelin' is in 1 chunk, 'delivery' in 4


def test_repeating_a_word_has_diminishing_returns():
    index = BM25Index([chunk("once", "alpha beta gamma delta"), chunk("ten", "alpha " * 10 + "beta gamma delta"),
                       chunk("filler", "completely different words here")])
    terms = ["alpha"]
    once, ten = index.score(terms, 0), index.score(terms, 1)
    assert ten > once and ten < 10 * once


def test_a_long_chunk_is_not_unfairly_favoured():
    short = chunk("short", "alpha beta")
    long = chunk("long", "alpha " + "filler " * 40)
    results = BM25Index([short, long]).search("alpha")
    assert results[0].chunk.id == "short"


def test_k_limits_the_number_of_results_and_ties_keep_file_order():
    chunks = [chunk(f"c{i}", "same words here") for i in range(5)]
    results = BM25Index(chunks).search("same", k=3)
    assert [r.chunk.id for r in results] == ["c0", "c1", "c2"]


def test_the_title_and_section_name_are_searchable():
    chunks = [chunk("a", "nothing relevant", section="Lost packages", title="Shipping Policy"),
              chunk("b", "nothing relevant either", section="Other", title="Other Policy")]
    assert BM25Index(chunks).search("lost packages")[0].chunk.id == "a"


def test_results_are_best_first():
    chunks = [chunk("one", "refund"), chunk("two", "refund refund policy"), chunk("none", "shipping")]
    scores = [r.score for r in BM25Index(chunks).search("refund")]
    assert scores == sorted(scores, reverse=True)