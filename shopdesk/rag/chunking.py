import re
from dataclasses import dataclass
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "policies"


@dataclass(frozen=True)
class Chunk:
    id: str          # unique name, e.g. "refund#refund-windows"
    source: str      # the file it came from, e.g. "refund.md"
    doc_title: str   # e.g. "Refund Policy"
    section: str     # e.g. "Refund windows"
    text: str        # the section's text, without its heading

    @property
    def search_text(self) -> str:
        """What the search indexes: the title and section name give every chunk its context."""
        return f"{self.doc_title}. {self.section}. {self.text}"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split an oversized section on blank lines into pieces of at most max_chars (where possible)."""
    pieces, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text):
        if current and len(current) + len(paragraph) + 2 > max_chars:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces


def split_markdown(source: str, markdown: str, max_chars: int = 1200) -> list[Chunk]:
    """
    Structure-aware chunking: one chunk per '## ' section, so each chunk is one idea with a name.
    The '# ' line is the document title. Text before the first '## ' becomes an 'Overview' section.
    A section longer than max_chars is split on blank lines.
    """
    doc_title = source
    sections = []                      # list of [section name, [lines]]
    current = ["Overview", []]
    for line in markdown.splitlines():
        if line.startswith("## "):
            sections.append(current)
            current = [line[3:].strip(), []]
        elif line.startswith("# ") and doc_title == source:
            doc_title = line[2:].strip()
        else:
            current[1].append(line)
    sections.append(current)

    stem = Path(source).stem
    chunks, seen = [], {}
    for name, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        for part_number, piece in enumerate(_split_long(body, max_chars), start=1):
            base = f"{stem}#{slugify(name)}"
            seen[base] = seen.get(base, 0) + 1
            chunk_id = base if seen[base] == 1 else f"{base}-{seen[base]}"
            chunks.append(Chunk(chunk_id, source, doc_title, name, piece))
    return chunks


def load_policy_chunks(directory=None, max_chars: int = 1200) -> list[Chunk]:
    """Read every .md file in the policy folder and return all chunks."""
    folder = Path(directory) if directory else POLICY_DIR
    chunks = []
    for path in sorted(folder.glob("*.md")):
        chunks += split_markdown(path.name, path.read_text(encoding="utf-8"), max_chars)
    return chunks