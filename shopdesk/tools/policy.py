from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from shopdesk.rag.factory import build_policy_index
from shopdesk.tools.common import ok, parse_args

NOTE_FOUND = (
    "These are the closest policy passages found. Answer ONLY from them, and only if they "
    "directly answer the question; otherwise say you do not have that information. "
    "Cite the source as given in cite_as."
)
NOTE_NOT_FOUND = (
    "No policy text matches this question. Do not answer from memory. Tell the customer you do not "
    "have that information and offer to hand them to a human agent."
)


class SearchPolicyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        ..., min_length=3, max_length=300,
        description="The question or topic to look up, in plain words, for example 'how long do refunds take'.",
    )
    max_results: int = Field(3, ge=1, le=5, description="How many passages to return (1-5).")


SEARCH_POLICY_SPEC = {
    "name": "search_policy",
    "description": (
        "Search the shop's written policies (refunds, shipping, warranty and defective items, "
        "escalation to a human) and return the most relevant passages with their source. Use it for ANY "
        "question about policy: refund timing, shipping times and costs, warranty, what happens next, "
        "how the shop works. Never answer policy questions from memory. If found is false, say you do "
        "not have that information. This does not look at any customer's data."
    ),
    "input_schema": SearchPolicyArgs.model_json_schema(),
}


@lru_cache(maxsize=1)
def _default_index():
    """Build the search index once and reuse it. Which search it is depends on POLICY_SEARCH."""
    return build_policy_index()


def search_policy(raw_args: dict, conn=None, index=None) -> dict:
    args, error = parse_args(SearchPolicyArgs, raw_args)
    if error:
        return error

    index = index or _default_index()
    results = index.search(args.query, k=args.max_results)
    passages = [
        {
            "cite_as": f"{r.chunk.doc_title}, {r.chunk.section}",
            "source_file": r.chunk.source,
            "text": r.chunk.text,
        }
        for r in results
    ]
    return ok({
        "found": bool(passages),
        "retriever": getattr(index, "name", "unknown"),
        "note": NOTE_FOUND if passages else NOTE_NOT_FOUND,
        "passages": passages,
    })