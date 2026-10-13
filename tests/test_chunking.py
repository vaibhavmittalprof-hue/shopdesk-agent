import re

from shopdesk.policy import APPROVAL_LIMIT_CENTS, REFUND_WINDOWS
from shopdesk.rag.chunking import load_policy_chunks, slugify, split_markdown

SAMPLE = """# Sample Policy

Intro text before any section.

## First section
Alpha beta.

## Second section
Gamma delta.

### A sub-heading stays inside its section
Epsilon.

## Empty section

## Third section
Zeta.
"""


def test_one_chunk_per_section_with_the_document_title():
    chunks = split_markdown("sample.md", SAMPLE)
    assert [c.section for c in chunks] == ["Overview", "First section", "Second section", "Third section"]
    assert all(c.doc_title == "Sample Policy" for c in chunks)
    assert all(c.source == "sample.md" for c in chunks)


def test_text_before_the_first_section_becomes_an_overview():
    chunks = split_markdown("sample.md", SAMPLE)
    assert "Intro text" in chunks[0].text


def test_sub_headings_stay_inside_their_section():
    second = split_markdown("sample.md", SAMPLE)[2]
    assert "Epsilon" in second.text and "A sub-heading" in second.text


def test_empty_sections_are_skipped():
    assert "Empty section" not in [c.section for c in split_markdown("sample.md", SAMPLE)]


def test_the_search_text_includes_the_title_and_section_name():
    chunk = split_markdown("sample.md", SAMPLE)[1]
    assert chunk.search_text.startswith("Sample Policy. First section. ")


def test_ids_are_readable_and_unique():
    chunks = split_markdown("sample.md", SAMPLE)
    assert chunks[1].id == "sample#first-section"
    assert len({c.id for c in chunks}) == len(chunks)


def test_a_long_section_is_split_on_blank_lines_and_gets_distinct_ids():
    paragraphs = [f"Paragraph number {i} " + "word " * 40 for i in range(6)]
    markdown = "# Long\n\n## Big section\n" + "\n\n".join(paragraphs)
    chunks = split_markdown("long.md", markdown, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
    assert chunks[1].id == "long#big-section-2"
    assert "Paragraph number 0" in chunks[0].text and "Paragraph number 5" in chunks[-1].text


def test_slugify():
    assert slugify("Refund windows") == "refund-windows"
    assert slugify("  What's NOT covered?  ") == "what-s-not-covered"


# ---------- the real policy documents ----------

def test_all_four_policy_documents_are_loaded():
    chunks = load_policy_chunks()
    assert {c.source for c in chunks} == {"refund.md", "shipping.md", "warranty.md", "escalation.md"}
    assert len({c.id for c in chunks}) == len(chunks)
    assert all(c.text.strip() for c in chunks)


def test_the_refund_windows_table_stays_in_one_chunk():
    windows = next(c for c in load_policy_chunks() if c.id == "refund#refund-windows")
    assert "| Electronics |" in windows.text and "| Clothing |" in windows.text


def test_the_policy_document_agrees_with_the_code():
    """The rulebook and the rule engine must say the same thing, or the agent will contradict its own tools."""
    windows = next(c for c in load_policy_chunks() if c.id == "refund#refund-windows").text
    labels = {"clothing": "Clothing", "home": "Home", "electronics": "Electronics"}
    for category, label in labels.items():
        standard, vip = REFUND_WINDOWS[category]
        row = next(line for line in windows.splitlines() if line.startswith(f"| {label} |"))
        assert f"{standard} days" in row and f"{vip} days" in row, row
    assert REFUND_WINDOWS["gift_card"] is None
    assert "Not refundable" in next(l for l in windows.splitlines() if l.startswith("| Gift cards |"))

    approval = next(c for c in load_policy_chunks() if c.id == "refund#approval").text
    assert f"{APPROVAL_LIMIT_CENTS:,}" in approval                      # "20,000 cents"
    assert f"${APPROVAL_LIMIT_CENTS // 100}.00" in approval              # "$200.00"


def test_every_ticket_reason_the_code_accepts_is_documented():
    from typing import get_args

    from shopdesk.tools.tickets import EscalateArgs

    reasons = get_args(EscalateArgs.model_fields["reason"].annotation)     # the allowed words
    assert len(reasons) == 4
    text = next(c for c in load_policy_chunks() if c.id == "escalation#ticket-reasons").text
    for reason in reasons:
        assert reason in text, reason