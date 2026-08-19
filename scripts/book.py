#!/usr/bin/env python3
"""Manifest-driven tooling for a book workspace.

    python3 scripts/book.py status [--json]
    python3 scripts/book.py scaffold
    python3 scripts/book.py lint [--json] [--strict]
    python3 scripts/book.py assemble [--out dist/manuscript.md]

Standard library only, so a clone of this template works with nothing installed
and with the plugin uninstalled. Python 3.11+ (tomllib).

Every check here is mechanical — something a machine can settle. Checks a
machine cannot settle are named in `lint --json` under "unenforceable" rather
than silently omitted, because a clean run that quietly skipped half the book
is the failure mode this file exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "book.toml"

STATUSES = ["planned", "briefed", "researched", "drafted", "reviewed", "final"]
DRAFTED = STATUSES.index("drafted")

# Markers a writing agent leaves behind when it did not have an answer. They are
# useful during drafting and fatal afterwards.
OPEN_MARKERS = re.compile(r"\[(?:TK|VERIFY|CITE|FIXME)\b[^\]]*\]|\bTODO\b")

FIGURE_DIRECTIVE = re.compile(r"^:::\s*figure\s+(\S+)", re.MULTILINE)

WORD_TOLERANCE = 0.25  # ±25% of a chapter's target before it is worth reporting

# Cross-chapter repetition detection. Ten-word shingles are long enough that a
# collision is almost never coincidence and almost always an agent restating
# something an earlier chapter already said.
SHINGLE = 10
SHINGLE_MIN_CHAPTERS = 2


class ManifestError(RuntimeError):
    pass


@dataclass
class Chapter:
    id: str
    slug: str
    title: str
    part: str = ""
    brief: str = ""
    word_target: int = 0
    status: str = "planned"
    research: list[str] = field(default_factory=list)
    figures: list[str] = field(default_factory=list)
    establishes: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)

    @property
    def manuscript_path(self) -> Path:
        return ROOT / "manuscript" / f"{self.id}-{self.slug}.md"

    @property
    def brief_path(self) -> Path:
        return ROOT / (self.brief or f"outline/briefs/{self.id}-{self.slug}.md")

    @property
    def rank(self) -> int:
        try:
            return STATUSES.index(self.status)
        except ValueError:
            raise ManifestError(f"{self.id}: unknown status {self.status!r}")

    def words(self) -> int:
        if not self.manuscript_path.exists():
            return 0
        return len(body_of(self.manuscript_path).split())


@dataclass
class Book:
    meta: dict
    production: dict
    voice: dict
    parts: list[dict]
    chapters: list[Chapter]


def load() -> Book:
    if not MANIFEST.exists():
        raise ManifestError(f"no manifest at {MANIFEST}")
    data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    chapters = [Chapter(**c) for c in data.get("chapter", [])]
    return Book(
        meta=data.get("book", {}),
        production=data.get("production", {}),
        voice=data.get("voice", {}),
        parts=data.get("part", []),
        chapters=chapters,
    )


def body_of(path: Path) -> str:
    """File text with any YAML front matter stripped."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def normalised_words(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # code blocks are quoted, not written
    return re.findall(r"[a-z0-9']+", text.lower())


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def cmd_status(book: Book, args) -> int:
    rows = []
    for ch in book.chapters:
        rows.append(
            {
                "id": ch.id,
                "part": ch.part,
                "title": ch.title,
                "status": ch.status,
                "words": ch.words(),
                "word_target": ch.word_target,
                "brief": ch.brief_path.exists(),
                "manuscript": ch.manuscript_path.exists(),
            }
        )

    written = sum(r["words"] for r in rows)
    target = book.meta.get("word_target") or sum(r["word_target"] for r in rows)
    by_status = Counter(r["status"] for r in rows)

    if args.json:
        print(
            json.dumps(
                {
                    "title": book.meta.get("title", ""),
                    "status": book.meta.get("status", ""),
                    "words_written": written,
                    "word_target": target,
                    "by_status": dict(by_status),
                    "chapters": rows,
                },
                indent=2,
            )
        )
        return 0

    print(f"{book.meta.get('title', '(untitled)')}  [{book.meta.get('status', '?')}]")
    pct = (100 * written / target) if target else 0
    print(f"{written:,} / {target:,} words ({pct:.0f}%)")
    print("  ".join(f"{s}:{by_status.get(s, 0)}" for s in STATUSES))
    print()
    for r in rows:
        flag = "b" if r["brief"] else "-"
        flag += "m" if r["manuscript"] else "-"
        bar = ""
        if r["word_target"]:
            bar = f"{r['words']:>6,}/{r['word_target']:<6,}"
        print(f"  {r['id']:<6} {flag}  {r['status']:<11} {bar}  {r['title']}")
    return 0


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------

BRIEF_STUB = """# Brief — {title}

> The contract handed to a chapter-writing subagent. It reads this, the style
> guide, and its research notes. It does not read other chapters. Everything it
> needs to not contradict the rest of the book has to be in here.

**Chapter** {id} · part {part} · target {word_target:,} words

## Argument

<!-- One paragraph. The single claim this chapter makes. If you cannot state it
     in one paragraph the chapter is two chapters. -->

## What the reader can do afterwards

<!-- Concrete and testable. "Understands X" is not an answer; "can size a spine
     from a page count" is. -->

## Assumed by this point

<!-- What earlier chapters have already established, so this one does not
     re-explain it. Mirror the `requires` keys from book.toml. -->

## Establishes

<!-- Terms, figures or claims introduced here for the first time. Mirror the
     `establishes` keys from book.toml. Later chapters may lean on these. -->

## Must cover

<!-- Bullet list. The writer may reorder and may add, but may not drop. -->

## Must not cover

<!-- Where the boundaries with adjacent chapters sit. This section prevents the
     overlap that shows up as repetition in the assembled manuscript. -->

## Sources

<!-- Files, URLs, research notes. A writer that needs a fact not reachable from
     this list must leave [VERIFY: ...] rather than invent one. -->

## Figures

<!-- graphics/specs/<id>.md entries this chapter renders, or none. -->
"""

MANUSCRIPT_STUB = """---
chapter: {id}
title: {title}
brief: {brief}
status: stub
---

# {title}

<!-- Drafted by a chapter-writing subagent from {brief}. Delete this comment. -->
"""


def cmd_scaffold(book: Book, args) -> int:
    made = []
    for ch in book.chapters:
        if not ch.brief_path.exists():
            ch.brief_path.parent.mkdir(parents=True, exist_ok=True)
            ch.brief_path.write_text(
                BRIEF_STUB.format(
                    title=ch.title,
                    id=ch.id,
                    part=ch.part or "-",
                    word_target=ch.word_target,
                ),
                encoding="utf-8",
            )
            made.append(str(ch.brief_path.relative_to(ROOT)))
        if ch.rank >= DRAFTED and not ch.manuscript_path.exists():
            ch.manuscript_path.parent.mkdir(parents=True, exist_ok=True)
            ch.manuscript_path.write_text(
                MANUSCRIPT_STUB.format(
                    id=ch.id,
                    title=ch.title,
                    brief=ch.brief_path.relative_to(ROOT),
                ),
                encoding="utf-8",
            )
            made.append(str(ch.manuscript_path.relative_to(ROOT)))

    if args.json:
        print(json.dumps({"created": made}, indent=2))
    elif made:
        for m in made:
            print(f"created {m}")
    else:
        print("nothing to scaffold")
    return 0


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

UNENFORCEABLE = [
    "Whether a claim is true. The linter checks that a source is cited, not that it says so.",
    "Whether the voice matches the style guide. That is the voice-auditor's job and it is a judgement.",
    "Whether a chapter delivers the argument its brief promised.",
    "Whether a figure shows the mechanism its spec describes.",
]


def _record_repeat(
    repeats: dict[str, set[str]],
    tokens: list[str],
    start: int,
    end: int,
    shingle_owners: dict[tuple[str, ...], set[str]],
) -> None:
    """Store one maximal repeated run, keyed by its text so it reports once."""
    phrase = " ".join(tokens[start:end])
    owners: set[str] = set()
    for i in range(start, max(start + 1, end - SHINGLE + 1)):
        owners |= shingle_owners.get(tuple(tokens[i : i + SHINGLE]), set())
    repeats.setdefault(phrase, set()).update(owners)


def cmd_lint(book: Book, args) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # -- structure ---------------------------------------------------------
    part_ids = {p.get("id") for p in book.parts}
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for ch in book.chapters:
        if ch.id in seen_ids:
            errors.append(f"{ch.id}: duplicate chapter id")
        seen_ids.add(ch.id)
        if ch.slug in seen_slugs:
            errors.append(f"{ch.id}: duplicate slug {ch.slug!r}")
        seen_slugs.add(ch.slug)
        if ch.part and ch.part not in part_ids:
            errors.append(f"{ch.id}: part {ch.part!r} is not declared in [[part]]")
        try:
            ch.rank
        except ManifestError as exc:
            errors.append(str(exc))

    # -- required files at each status ------------------------------------
    for ch in book.chapters:
        if ch.status != "planned" and not ch.brief_path.exists():
            errors.append(f"{ch.id}: status {ch.status} but no brief at {ch.brief_path.relative_to(ROOT)}")
        if ch.rank >= DRAFTED and not ch.manuscript_path.exists():
            errors.append(f"{ch.id}: status {ch.status} but no manuscript at {ch.manuscript_path.relative_to(ROOT)}")
        for note in ch.research:
            if not (ROOT / note).exists():
                errors.append(f"{ch.id}: research note {note} does not exist")
        for figure in ch.figures:
            if not (ROOT / figure).exists():
                errors.append(f"{ch.id}: figure spec {figure} does not exist")

    # -- continuity ordering ----------------------------------------------
    established_by: dict[str, str] = {}
    for ch in book.chapters:
        for key in ch.requires:
            if key not in established_by:
                errors.append(
                    f"{ch.id}: requires {key!r}, which no earlier chapter establishes"
                )
        for key in ch.establishes:
            if key in established_by:
                errors.append(
                    f"{ch.id}: establishes {key!r}, already established by {established_by[key]}"
                )
            else:
                established_by[key] = ch.id

    ledger = ROOT / "continuity.md"
    if ledger.exists():
        ledger_text = ledger.read_text(encoding="utf-8")
        for key, owner in established_by.items():
            if key not in ledger_text:
                warnings.append(f"{owner}: establishes {key!r} but it is not in continuity.md")

    # -- drafted prose -----------------------------------------------------
    shingle_owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
    chapter_tokens: dict[str, list[str]] = {}
    for ch in book.chapters:
        if ch.rank < DRAFTED or not ch.manuscript_path.exists():
            continue
        text = body_of(ch.manuscript_path)

        open_markers = OPEN_MARKERS.findall(text)
        if open_markers:
            where = errors if ch.status in ("reviewed", "final") else warnings
            where.append(
                f"{ch.id}: {len(open_markers)} unresolved marker(s): "
                + ", ".join(sorted(set(open_markers))[:4])
            )

        heading = next((l for l in text.splitlines() if l.startswith("# ")), None)
        if heading is None:
            errors.append(f"{ch.id}: manuscript has no H1")
        elif heading[2:].strip() != ch.title:
            warnings.append(
                f"{ch.id}: H1 {heading[2:].strip()!r} does not match manifest title {ch.title!r}"
            )

        for fig in FIGURE_DIRECTIVE.findall(text):
            spec = ROOT / "graphics" / "specs" / f"{fig}.md"
            if not spec.exists():
                errors.append(f"{ch.id}: renders figure {fig!r} with no spec at {spec.relative_to(ROOT)}")

        if ch.word_target:
            words = len(text.split())
            low = ch.word_target * (1 - WORD_TOLERANCE)
            high = ch.word_target * (1 + WORD_TOLERANCE)
            if words < low or words > high:
                warnings.append(
                    f"{ch.id}: {words:,} words against a target of {ch.word_target:,}"
                )

        tokens = normalised_words(text)
        chapter_tokens[ch.id] = tokens
        for i in range(len(tokens) - SHINGLE):
            shingle_owners[tuple(tokens[i : i + SHINGLE])].add(ch.id)

    # Overlapping shingles describe one passage, not ten. Merge each chapter's
    # consecutive repeated positions into maximal runs and report each distinct
    # passage once, however many chapters it turns up in.
    repeats: dict[str, set[str]] = {}
    for cid, tokens in chapter_tokens.items():
        start = None
        for i in range(len(tokens) - SHINGLE + 1):
            owners = shingle_owners.get(tuple(tokens[i : i + SHINGLE]), set())
            repeated = len(owners) >= SHINGLE_MIN_CHAPTERS
            if repeated and start is None:
                start = i
            elif not repeated and start is not None:
                _record_repeat(repeats, tokens, start, i + SHINGLE - 1, shingle_owners)
                start = None
        if start is not None:
            _record_repeat(repeats, tokens, start, len(tokens), shingle_owners)

    for phrase, owners in sorted(repeats.items())[:15]:
        excerpt = phrase if len(phrase) <= 90 else phrase[:90].rsplit(" ", 1)[0] + "…"
        warnings.append(f"repeated across {', '.join(sorted(owners))}: “{excerpt}”")
    if len(repeats) > 15:
        warnings.append(f"({len(repeats) - 15} further repeated passages not listed)")

    if args.strict:
        errors.extend(warnings)
        warnings = []

    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "unenforceable": UNENFORCEABLE}, indent=2))
    else:
        for w in warnings:
            print(f"warn  {w}")
        for e in errors:
            print(f"ERROR {e}")
        if not errors and not warnings:
            print("clean")
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------


def cmd_assemble(book: Book, args) -> int:
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    pieces: list[str] = []
    meta = book.meta
    pieces.append(f"# {meta.get('title', 'Untitled')}\n")
    if meta.get("subtitle"):
        pieces.append(f"## {meta['subtitle']}\n")
    if meta.get("author"):
        pieces.append(f"*{meta['author']}*\n")
    if meta.get("snapshot_date"):
        pieces.append(f"Content is current as of {meta['snapshot_date']}.\n")

    by_part: dict[str, list[Chapter]] = defaultdict(list)
    loose: list[Chapter] = []
    for ch in book.chapters:
        (by_part[ch.part] if ch.part else loose).append(ch)

    def emit(ch: Chapter) -> None:
        if not ch.manuscript_path.exists():
            pieces.append(f"\n<!-- {ch.id} {ch.title}: not drafted -->\n")
            return
        pieces.append("\n" + body_of(ch.manuscript_path).strip() + "\n")

    for part in book.parts:
        chapters = by_part.get(part.get("id", ""), [])
        if not chapters:
            continue
        pieces.append(f"\n\n# Part — {part.get('title', '')}\n")
        for ch in chapters:
            emit(ch)
    for ch in loose:
        emit(ch)

    out.write_text("\n".join(pieces), encoding="utf-8")

    drafted = [c for c in book.chapters if c.manuscript_path.exists()]
    words = sum(c.words() for c in drafted)

    sidecar = out.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "snapshot_date": meta.get("snapshot_date", ""),
                "profile": book.production.get("profile", ""),
                "handoff": book.production.get("handoff", ""),
                "words": words,
                "chapters": [
                    {"id": c.id, "title": c.title, "part": c.part, "status": c.status}
                    for c in book.chapters
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote {out.relative_to(ROOT)} — {len(drafted)}/{len(book.chapters)} chapters, {words:,} words")
    print(f"wrote {sidecar.relative_to(ROOT)} — production handoff metadata")
    return 0


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="what is drafted, what is not")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("scaffold", help="create missing briefs and manuscript stubs")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("lint", help="mechanical gates over the manifest and drafted prose")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="warnings become errors")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("assemble", help="concatenate drafted chapters into dist/")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default="dist/manuscript.md")
    p.set_defaults(func=cmd_assemble)

    args = parser.parse_args()
    try:
        book = load()
    except (ManifestError, tomllib.TOMLDecodeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    return args.func(book, args)


if __name__ == "__main__":
    sys.exit(main())
