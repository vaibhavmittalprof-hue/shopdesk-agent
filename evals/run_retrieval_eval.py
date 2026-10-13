"""
Measure how well the policy SEARCH finds the right chunk (no AI involved).

    python -m evals.run_retrieval_eval                                  # keyword search only
    python -m evals.run_retrieval_eval --embedder fastembed             # + meaning search and hybrid
    python -m evals.run_retrieval_eval --embedder fastembed --embedder fastembed:sentence-transformers/all-MiniLM-L6-v2

For each question in evals/retrieval_questions.jsonl we know which chunk(s) hold the answer.
We run each search and ask: did a correct chunk appear in the top 1 / top 3 / top 5?
"""
import argparse
import json
from pathlib import Path

from shopdesk.rag.bm25 import BM25Index
from shopdesk.rag.chunking import load_policy_chunks
from shopdesk.rag.dense import DenseIndex
from shopdesk.rag.embeddings import EmbeddingsUnavailable, make_embedder
from shopdesk.rag.hybrid import HybridIndex

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


def print_scores(results):
    print(f"  {'search':<46}{'recall@1':>9}{'recall@3':>9}{'recall@5':>9}{'MRR':>7}")
    for label, scores in results.items():
        r = scores["recall"]
        print(f"  {label:<46}{r[1]:>9.0%}{r[3]:>9.0%}{r[5]:>9.0%}{scores['mrr']:>7.2f}")


def print_rank_table(results, questions):
    """For each question, at what position did each search put the right chunk? ('-' = not in the top 5)"""
    labels = list(results)
    print("\nRANK OF THE RIGHT CHUNK, PER QUESTION   ('-' = not in the top 5)")
    print(f"  {'':<6}" + "".join(f"{f'[{i}]':>6}" for i in range(1, len(labels) + 1)) + "   question")
    for number, q in enumerate(questions):
        ranks = [results[label]["details"][number]["rank"] for label in labels]
        cells = "".join(f"{(str(r) if r else '-'):>6}" for r in ranks)
        flag = "  <--" if len({bool(r and r <= 3) for r in ranks}) > 1 else ""      # the searches disagree
        print(f"  {q['id']:<6}{cells}   {q['question'][:60]}{flag}")
    for i, label in enumerate(labels, start=1):
        print(f"  [{i}] {label}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate the policy search.")
    parser.add_argument("--embedder", action="append", default=[],
                        help="e.g. fastembed or fastembed:<model>. Repeat to compare several models.")
    args = parser.parse_args()

    chunks, questions = load_policy_chunks(), load_questions()
    print(f"{len(chunks)} chunks, {len(questions)} questions\n")

    bm25 = BM25Index(chunks)
    searches = {
        "BM25, plain words": BM25Index(chunks, stem=False, drop_stopwords=False).search,
        "BM25, stemming + stop words": bm25.search,
    }
    for spec in args.embedder:
        try:
            embedder = make_embedder(spec)
        except EmbeddingsUnavailable as exc:
            print(f"  (skipping '{spec}': {exc})")
            continue
        dense = DenseIndex(chunks, embedder)
        searches[f"Meaning search: {embedder.name}"] = dense.search
        searches[f"Hybrid: BM25 + {embedder.name}"] = HybridIndex(bm25, dense).search

    results = {label: evaluate(search, questions) for label, search in searches.items()}
    print("RESULTS")
    print_scores(results)
    print_rank_table(results, questions)

    # best MRR wins; on a tie, prefer the later (more advanced) search
    best_label = max(results, key=lambda label: (round(results[label]["mrr"], 6), results[label]["recall"][3],
                                                 list(results).index(label)))
    print(f"\nBEST BY MRR: {best_label}")
    misses = [d for d in results[best_label]["details"] if d["rank"] is None or d["rank"] > 3]
    print("QUESTIONS IT STILL MISSES (right chunk not in the top 3)")
    for d in misses:
        print(f"  {d['id']}: {d['question']}\n    wanted: {', '.join(d['expected'])}"
              f"   top 3 was: {', '.join(d['retrieved'][:3]) or '(nothing)'}")
    if not misses:
        print("  none")


if __name__ == "__main__":
    main()