"""Turning documents into retrievable pieces.

Two corpora, two strategies, and the difference is the point:

- Policy documents are structured markdown. Splitting on headers keeps each
  chunk inside one section and records the header path as metadata, so a hit
  can be cited as "Roads SOP › Response norms" rather than "chunk 17".
- Case records (resolved complaints, from Phase 2b onward) are short and
  self-contained. One record is one chunk; splitting them would only separate
  a description from its outcome.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_HEADER = re.compile(r"^(#{1,3})\s+(.*)$", re.M)


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    chunk_id: str
    metadata: dict = field(default_factory=dict)


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def _chunk_id(source: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha1(f"{source}:{ordinal}:{text}".encode()).hexdigest()[:12]
    return f"{source}#{ordinal}-{digest}"


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    """Iterative split by paragraph, then line, then sentence, then hard cut, with overlap."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # prefer to break at a paragraph, then a line, then a sentence, then a space
            for sep in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, start, end)
                if cut > start + max_chars // 2:
                    end = cut + len(sep)
                    break
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        # Snap the overlap to a line boundary too, so a table row that made
        # it whole into this chunk isn't handed to the next chunk split down
        # its middle.
        newline = text.find("\n", next_start, end)
        start = newline + 1 if newline != -1 else next_start
    return [p for p in pieces if p]


def chunk_markdown(
    text: str, source: str, *, max_chars: int = 1800, overlap: int = 200
) -> list[Chunk]:
    text = text.replace("\r\n", "\n")
    front, body = _parse_front_matter(text)
    chunks: list[Chunk] = []
    header_path: list[str] = []
    ordinal = 0

    # Walk sections: each header starts a new section; text before any header is one.
    positions = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip()) for m in _HEADER.finditer(body)]
    boundaries = [(0, positions[0][0] if positions else len(body), None)]
    for i, (start, end, level, title) in enumerate(positions):
        nxt = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        boundaries.append((end, nxt, (level, title)))

    for start, end, header in boundaries:
        if header:
            level, title = header
            header_path = header_path[: level - 1] + [title]
        section = body[start:end].strip()
        if not section:
            continue
        for piece in _split_long(section, max_chars, overlap):
            chunks.append(Chunk(
                text=piece,
                source=source,
                chunk_id=_chunk_id(source, ordinal, piece),
                metadata={**front, "headers": list(header_path)},
            ))
            ordinal += 1
    return chunks


def chunk_record(text: str, source: str, metadata: dict) -> list[Chunk]:
    """A case record is one chunk. Splitting it would separate cause from outcome."""
    return [Chunk(text=text, source=source, chunk_id=_chunk_id(source, 0, text),
                  metadata=dict(metadata))]


def load_corpus(directory: Path = CORPUS_DIR) -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(directory.glob("*.md"))]
