"""Structure-aware chunking.

Markdown documents are split into sections at headings; each chunk carries its section heading so
citations stay meaningful ("Response times — Critical requests ..."). HTML comments are dropped.
Long sections are split at paragraph, then sentence, then word boundaries with overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    document: str
    title: str
    text: str
    index: int


def _pieces(text: str, size: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCES.split(paragraph):
            while len(sentence) > size:
                cut = sentence.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    return pieces


def chunk_text(text: str, *, size: int = 800, overlap: int = 120) -> list[str]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: list[str] = []
    current = ""
    for piece in _pieces(text, size):
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            if tail and " " in tail:
                tail = tail[tail.find(" ") + 1 :]
            current = f"{tail} {piece}".strip() if tail else piece
            if len(current) > size:
                current = piece
        else:
            current = piece
    if current:
        chunks.append(current)
    return chunks


def split_sections(text: str) -> tuple[str | None, list[tuple[str | None, str]]]:
    """Return (document title, [(section heading, section body), ...])."""
    title: str | None = None
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in _COMMENT.sub("", text).splitlines():
        match = _HEADING.match(line)
        if match:
            heading = match.group(2).strip()
            if len(match.group(1)) == 1 and title is None:
                title = heading
                continue
            sections.append((heading, []))
        else:
            sections[-1][1].append(line)
    return title, [(heading, "\n".join(lines).strip()) for heading, lines in sections if "\n".join(lines).strip()]


def chunk_document(source: str, path: str, text: str, *, size: int, overlap: int) -> list[Chunk]:
    stem = PurePosixPath(path).stem
    title, sections = split_sections(text)
    title = title or stem.replace("_", " ").replace("-", " ").title()
    chunks: list[Chunk] = []
    for heading, body in sections:
        prefix = f"{heading} — " if heading else ""
        for piece in chunk_text(body, size=max(size - len(prefix), overlap + 50), overlap=overlap):
            chunks.append(
                Chunk(
                    id=f"{source}:{stem}:{len(chunks)}",
                    source=source,
                    document=path,
                    title=title,
                    text=prefix + piece,
                    index=len(chunks),
                )
            )
    return chunks
