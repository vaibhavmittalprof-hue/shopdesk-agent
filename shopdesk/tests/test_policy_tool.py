import pytest

from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import Chunk, load_policy_chunks
from shopdesk.tools.policy import SEARCH_POLICY_SPEC, search_policy
from shopdesk.tools.registry import TOOLS, run_tool


def test_it_finds_the_refund_timing_passage():
    data = search_policy({"query": "how long do refunds take"})["data"]
    assert data["found"] is True
    assert data["passages"][0]["cite_as"] == "Refund Policy, Refund timing"
    assert "5 to 7 business days" in data["passages"][0]["text"]


def test_every_passage_says_where_it_came_from():
    for passage in search_policy({"query": "express shipping cost"})["data"]["passages"]:
        assert passage["cite_as"] and passage["source_file"].endswith(".md") and passage["text"].strip()


def test_scores_are_not_shown_to_the_model():
    passage = search_policy({"query": "express shipping cost"})["data"]["passages"][0]
    assert set(passage) == {"cite_as", "source_file", "text"}


def test_max_results_is_respected():
    assert len(search_policy({"query": "refund", "max_results": 1})["data"]["passages"]) == 1
    assert len(search_policy({"query": "refund", "max_results": 4})["data"]["passages"]) <= 4


def test_a_question_with_no_matching_words_finds_nothing_and_says_not_to_guess():
    data = search_policy({"query": "cryptocurrency zebra"})["data"]
    assert data["found"] is False and data["passages"] == []
    assert "do not have that information" in data["note"]


def test_when_something_is_found_the_note_tells_the_model_to_use_it_only_if_it_answers():
    note = search_policy({"query": "refund timing"})["data"]["note"]
    assert "ONLY" in note and "directly answer" in note


def test_every_answerable_question_gets_some_passages():
    """Design choice, measured in M5: a raw keyword score cannot tell 'no answer' from 'weak answer',
    so the tool returns whatever matches and the model decides whether it answers the question."""
    from evals.run_retrieval_eval import load_questions
    for q in load_questions():
        assert search_policy({"query": q["question"]})["data"]["found"] is True, q["id"]


def test_bad_input_is_rejected_without_raising():
    for bad in [{}, {"query": "ab"}, {"query": "x" * 301}, {"query": "valid query", "max_results": 0},
                {"query": "valid query", "max_results": 6}, {"query": "valid query", "extra": 1}]:
        result = search_policy(bad)
        assert result["ok"] is False and result["error"]["code"] == "INVALID_INPUT", bad


def test_it_can_search_a_different_index():
    chunks = [Chunk("x#one", "x.md", "Pets", "Dogs", "Dogs must be leashed."),
              Chunk("x#two", "x.md", "Pets", "Cats", "Cats may roam.")]
    data = search_policy({"query": "leashed dogs"}, index=BM25Index(chunks))["data"]
    assert data["passages"][0]["cite_as"] == "Pets, Dogs"


def test_it_needs_no_database():
    assert search_policy({"query": "shipping costs"}, conn=None)["ok"] is True


def test_it_is_registered_and_runs_through_the_registry():
    assert "search_policy" in TOOLS
    assert run_tool("search_policy", {"query": "lost package"})["ok"] is True


def test_the_description_forbids_answering_from_memory():
    assert "Never answer policy questions from memory" in SEARCH_POLICY_SPEC["description"]


def test_the_index_is_built_once():
    from shopdesk.tools import policy
    assert policy._default_index() is policy._default_index()
