from types import SimpleNamespace

from evals.run_retrieval_eval import evaluate, load_questions
from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import load_policy_chunks


def fake_search(answers):
    """A pretend search that returns the chunk ids listed for each question."""
    def search(question, k):
        return [SimpleNamespace(chunk=SimpleNamespace(id=cid)) for cid in answers[question][:k]]
    return search


QUESTIONS = [
    {"id": "a", "question": "first", "expected": ["right"]},
    {"id": "b", "question": "second", "expected": ["right"]},
    {"id": "c", "question": "third", "expected": ["right", "also-right"]},
    {"id": "d", "question": "fourth", "expected": ["right"]},
]


def test_recall_and_mrr_are_computed_from_the_rank_of_the_first_correct_chunk():
    search = fake_search({
        "first": ["right", "x", "y"],                  # rank 1
        "second": ["x", "y", "right"],                 # rank 3
        "third": ["x", "also-right", "y"],             # rank 2 (either expected chunk counts)
        "fourth": ["x", "y", "z", "w", "v"],           # never found
    })
    scores = evaluate(search, QUESTIONS, ks=(1, 3, 5))
    assert scores["recall"] == {1: 0.25, 3: 0.75, 5: 0.75}
    assert round(scores["mrr"], 4) == round((1 + 1 / 3 + 1 / 2 + 0) / 4, 4)
    assert [d["rank"] for d in scores["details"]] == [1, 3, 2, None]


def test_a_search_that_returns_nothing_scores_zero():
    scores = evaluate(lambda q, k: [], QUESTIONS)
    assert scores["recall"][5] == 0 and scores["mrr"] == 0


# ---------- the real question file ----------

def test_the_question_file_is_sound():
    questions = load_questions()
    assert len(questions) >= 20
    assert len({q["id"] for q in questions}) == len(questions)
    chunk_ids = {c.id for c in load_policy_chunks()}
    for q in questions:
        assert q["question"].strip() and q["expected"], q["id"]
        for cid in q["expected"]:
            assert cid in chunk_ids, f"{q['id']} expects '{cid}', which does not exist"


def test_the_search_does_not_get_worse():
    """A floor under the retrieval quality: if a change to the documents or the search drops below
    these numbers, this test fails and tells you before the agent does."""
    index = BM25Index(load_policy_chunks())
    scores = evaluate(index.search, load_questions())
    assert scores["recall"][5] >= 0.90, scores["recall"]
    assert scores["mrr"] >= 0.80, scores["mrr"]