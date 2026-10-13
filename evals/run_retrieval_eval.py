"""
Measure how well the policy SEARCH finds the right chunk (no AI involved).

    python -m evals.run_retrieval_eval

For each question in evals/retrieval_questions.jsonl we know which chunk(s) hold the answer.
We run the search and ask: did a correct chunk appear in the top 1 / top 3 / top 5?
"""
import json
from pathlib import Path

from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import load_policy_chunks

QUESTIONS_PATH = Path(__file__).parent / "retrieval_questions.jsonl"
KS = (1, 3, 5)


def load_questions(path=QUESTIONS_PATH):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def evaluate(search, questions, ks=KS):
    """
    search(question, k) -> list of results (best first), each with .chunk.id
    Returns recall@k (share of questions whose answer chunk is in the top k), MRR, and the details.
    """
    hits = {k: 0 for k in ks}
    reciprocal_sum = 0.0
    details = []
    for q in questions:
        results = search(q["question"], max(ks))
        retrieved = [r.chunk.id for r in results]
        expected = set(q["expected"])
        rank = next((position for position, cid in enumerate(retrieved, start=1) if cid in expected), None)
        for k in ks:
            if rank is not None and rank <= k:
                hits[k] += 1
        reciprocal_sum += 1 / rank if rank else 0.0
        details.append({"id": q["id"], "question": q["question"], "expected": q["expected"],
                        "retrieved": retrieved, "rank": rank})
    n = len(questions)
    return {"n": n, "recall": {k: hits[k] / n for k in ks}, "mrr": reciprocal_sum / n, "details": details}


def print_scores(label, scores):
    recall = "   ".join(f"recall@{k} {v:.0%}" for k, v in scores["recall"].items())
    print(f"  {label:<34}{recall}   MRR {scores['mrr']:.2f}")


def main():
    chunks = load_policy_chunks()
    questions = load_questions()
    print(f"{len(chunks)} chunks, {len(questions)} questions\n")

    naive = BM25Index(chunks, stem=False, drop_stopwords=False)
    better = BM25Index(chunks, stem=True, drop_stopwords=True)
    naive_scores = evaluate(naive.search, questions)
    better_scores = evaluate(better.search, questions)

    print("RESULTS")
    print_scores("BM25, plain words", naive_scores)
    print_scores("BM25, stemming + stop words", better_scores)

    print("\nQUESTIONS WHERE THE RIGHT CHUNK IS NOT IN THE TOP 3 (stemming + stop words)")
    misses = [d for d in better_scores["details"] if d["rank"] is None or d["rank"] > 3]
    for d in misses:
        found = f"rank {d['rank']}" if d["rank"] else "not found in the top 5"
        print(f"\n  {d['id']}: {d['question']}")
        print(f"    wanted:    {', '.join(d['expected'])}   ({found})")
        print(f"    top 3 was: {', '.join(d['retrieved'][:3]) or '(nothing matched)'}")
    if not misses:
        print("  none")

    print("\nQUESTIONS THAT STEMMING + STOP WORDS IMPROVED")
    changes = [(a, b) for a, b in zip(naive_scores["details"], better_scores["details"])
               if (a["rank"] or 99) != (b["rank"] or 99)]
    better_ones = [(a, b) for a, b in changes if (b["rank"] or 99) < (a["rank"] or 99)]
    worse_ones = [(a, b) for a, b in changes if (b["rank"] or 99) > (a["rank"] or 99)]
    for a, b in better_ones:
        print(f"  {b['id']}: rank {a['rank'] or 'not found'} -> {b['rank'] or 'not found'}   {b['question']}")
    if not better_ones:
        print("  none")

    print("\nQUESTIONS THAT GOT WORSE")
    for a, b in worse_ones:
        print(f"  {b['id']}: rank {a['rank'] or 'not found'} -> {b['rank'] or 'not found'}   {b['question']}")
    if not worse_ones:
        print("  none")


if __name__ == "__main__":
    main()