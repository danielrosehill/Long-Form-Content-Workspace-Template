#!/usr/bin/env python3
"""Manifest-driven tooling for a long-form content workspace.

One pipeline, four output types (`[output] type` in longform.toml):

    book        manuscript -> typeset body -> print-geometry handoff
    report      manuscript -> research report PDF (pandoc + typst)
    screenplay  Fountain units -> assembled .fountain -> PDF (external renderer)
    audiobook   manuscript -> spoken script -> per-chapter TTS -> chaptered .m4b

Definition, planning, drafting and review are identical for all four; only the
end of the chain differs.

    python3 scripts/longform.py status [--json]
    python3 scripts/longform.py scaffold
    python3 scripts/longform.py lint [--json] [--strict]
    python3 scripts/longform.py seams [--layer manuscript|script] [--words N] [--json]
    python3 scripts/longform.py assemble
    python3 scripts/longform.py export                 # report / screenplay PDF
    python3 scripts/longform.py script-lint [--json] [--strict]   # audiobook
    python3 scripts/longform.py render [--only ID ...] [--force] [--dry-run]
    python3 scripts/longform.py audio-assemble [--dry-run]

Standard library only, so a clone of this template works with nothing installed
and with the plugin uninstalled. Python 3.11+ (tomllib). `export`, `render` and
`audio-assemble` shell out to pandoc / typst / ffmpeg / your TTS command, and say
so plainly when one is missing.

Every check here is mechanical. Checks a machine cannot settle are named in
`lint --json` under "unenforceable" rather than silently omitted, because a
clean run that quietly skipped half the work is the failure mode this file
exists to prevent.

A workspace created before the rename (book.toml with a [book] table) still
loads: the manifest falls back to book.toml and [book] is read as [project].
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAMES = ["longform.toml", "book.toml"]  # second is the pre-rename name

TYPES = ["book", "report", "screenplay", "audiobook"]
STATUSES = ["planned", "briefed", "researched", "drafted", "reviewed", "final"]
DRAFTED = STATUSES.index("drafted")

# Markers a writing agent leaves behind when it did not have an answer. They are
# useful during drafting and fatal afterwards.
OPEN_MARKERS = re.compile(r"\[(?:TK|VERIFY|CITE|FIXME)\b[^\]]*\]|\bTODO\b")

FIGURE_DIRECTIVE = re.compile(r"^:::\s*figure\s+(\S+)", re.MULTILINE)

WORD_TOLERANCE = 0.25  # ±25% of a unit's target before it is worth reporting

# Cross-unit repetition detection. Ten-word shingles are long enough that a
# collision is almost never coincidence and almost always an agent restating
# something an earlier unit already said.
SHINGLE = 10
SHINGLE_MIN_CHAPTERS = 2

SEAM_WORDS = 350  # words taken from each side of a seam


class ManifestError(RuntimeError):
    pass


@dataclass
class Chapter:
    """One unit of work: a chapter, a report section, a screenplay sequence."""

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
    ext: str = ".md"  # set from the output type at load time

    @property
    def stem(self) -> str:
        return f"{self.id}-{self.slug}"

    @property
    def manuscript_path(self) -> Path:
        return ROOT / "manuscript" / f"{self.stem}{self.ext}"

    @property
    def brief_path(self) -> Path:
        return ROOT / (self.brief or f"outline/briefs/{self.stem}.md")

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
class Project:
    manifest: Path
    meta: dict
    output: dict
    production: dict
    voice: dict
    audio: dict
    parts: list[dict]
    chapters: list[Chapter]

    @property
    def type(self) -> str:
        return self.output.get("type", "book")

    # -- audiobook paths --------------------------------------------------
    @property
    def script_ext(self) -> str:
        return ".ssml" if self.audio.get("format", "plain") == "ssml" else ".txt"

    def script_path(self, ch: Chapter) -> Path:
        return ROOT / "audio" / "script" / f"{ch.stem}{self.script_ext}"

    def audio_path(self, ch: Chapter) -> Path:
        ext = self.audio.get("render_ext", "mp3").lstrip(".")
        return ROOT / "audio" / "chapters" / f"{ch.stem}.{ext}"


def find_manifest() -> Path:
    for name in MANIFEST_NAMES:
        if (ROOT / name).exists():
            return ROOT / name
    raise ManifestError(f"no manifest ({' or '.join(MANIFEST_NAMES)}) in {ROOT}")


def load() -> Project:
    manifest = find_manifest()
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    output = data.get("output", {})
    kind = output.get("type", "book")
    if kind not in TYPES:
        raise ManifestError(f"[output] type {kind!r} is not one of {', '.join(TYPES)}")
    ext = ".fountain" if kind == "screenplay" else ".md"
    chapters = [Chapter(**c, ext=ext) for c in data.get("chapter", [])]
    return Project(
        manifest=manifest,
        meta=data.get("project", data.get("book", {})),
        output=output,
        production=data.get("production", {}),
        voice=data.get("voice", {}),
        audio=data.get("audio", {}),
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


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def emit(args, payload: dict, lines: list[str]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        for line in lines:
            print(line)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def cmd_status(pj: Project, args) -> int:
    rows = []
    audio = pj.type == "audiobook"
    for ch in pj.chapters:
        row = {
            "id": ch.id,
            "part": ch.part,
            "title": ch.title,
            "status": ch.status,
            "words": ch.words(),
            "word_target": ch.word_target,
            "brief": ch.brief_path.exists(),
            "manuscript": ch.manuscript_path.exists(),
        }
        if audio:
            row["script"] = pj.script_path(ch).exists()
            row["audio"] = pj.audio_path(ch).exists()
        rows.append(row)

    written = sum(r["words"] for r in rows)
    target = pj.meta.get("word_target") or sum(r["word_target"] for r in rows)
    by_status = Counter(r["status"] for r in rows)
    wpm = int(pj.audio.get("words_per_minute", 155))

    if args.json:
        out = {
            "title": pj.meta.get("title", ""),
            "type": pj.type,
            "status": pj.meta.get("status", ""),
            "words_written": written,
            "word_target": target,
            "by_status": dict(by_status),
            "chapters": rows,
        }
        if audio:
            out["estimated_minutes"] = round(written / wpm)
        print(json.dumps(out, indent=2))
        return 0

    print(f"{pj.meta.get('title', '(untitled)')}  [{pj.type} · {pj.meta.get('status', '?')}]")
    pct = (100 * written / target) if target else 0
    line = f"{written:,} / {target:,} words ({pct:.0f}%)"
    if audio:
        line += f" · about {written / wpm / 60:.1f} h spoken at {wpm} wpm"
    print(line)
    print("  ".join(f"{s}:{by_status.get(s, 0)}" for s in STATUSES))
    print("flags: b brief · m manuscript" + (" · s spoken script · a rendered audio" if audio else ""))
    print()
    for r in rows:
        flag = ("b" if r["brief"] else "-") + ("m" if r["manuscript"] else "-")
        if audio:
            flag += ("s" if r["script"] else "-") + ("a" if r["audio"] else "-")
        bar = f"{r['words']:>6,}/{r['word_target']:<6,}" if r["word_target"] else ""
        print(f"  {r['id']:<6} {flag}  {r['status']:<11} {bar}  {r['title']}")
    return 0


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------

BRIEF_STUB = """# Brief — {title}

> The contract handed to a writing subagent. It reads this, the style guide,
> and its research notes. It does not read other units. Everything it needs to
> not contradict the rest of the work has to be in here.

**Unit** {id} · part {part} · target {word_target:,} words

## Argument

<!-- One paragraph. The single claim (or, for a screenplay sequence, the single
     dramatic turn) this unit makes. If it takes two, it is two units. -->

## What the reader can do afterwards

<!-- Concrete and testable. For a screenplay: what the audience now knows or
     feels that it did not at the start of the sequence. -->

## Assumed by this point

<!-- What earlier units have already established, so this one does not
     re-explain it. Mirror the `requires` keys from longform.toml. -->

## Establishes

<!-- Terms, figures, claims, characters or locations introduced here for the
     first time. Mirror the `establishes` keys. Later units may lean on these. -->

## Must cover

<!-- Bullet list. The writer may reorder and may add, but may not drop. -->

## Must not cover

<!-- Where the boundaries with adjacent units sit. This section prevents the
     overlap that shows up as repetition in the assembled work. -->

## Seams

<!-- The joins, decided here so two writers who never read each other still
     meet. The seam-reviewer checks the drafted joins against these lines.

     Picks up from: the state the previous unit leaves the reader in — the last
       point made, the question left open, for a screenplay the last image and
       where every character in the next scene was left.
     Hands off to: the state this unit must leave the reader in, and what it
       must NOT do on the way out (no recap, no preview of the next unit). -->

Picks up from:

Hands off to:

## Sources

<!-- Files, URLs, research notes. A writer that needs a fact not reachable from
     this list must leave [VERIFY: ...] rather than invent one. -->

## Figures

<!-- graphics/specs/<id>.md entries this unit renders, or none. -->
"""

MANUSCRIPT_STUB = """---
chapter: {id}
title: {title}
brief: {brief}
status: stub
---

# {title}

<!-- Drafted by a writing subagent from {brief}. Delete this comment. -->
"""

FOUNTAIN_STUB = """# {title}

/* Drafted by a writing subagent from {brief}. Delete this note. */
"""


def cmd_scaffold(pj: Project, args) -> int:
    made = []
    for ch in pj.chapters:
        if not ch.brief_path.exists():
            ch.brief_path.parent.mkdir(parents=True, exist_ok=True)
            ch.brief_path.write_text(
                BRIEF_STUB.format(
                    title=ch.title, id=ch.id, part=ch.part or "-", word_target=ch.word_target
                ),
                encoding="utf-8",
            )
            made.append(rel(ch.brief_path))
        if ch.rank >= DRAFTED and not ch.manuscript_path.exists():
            ch.manuscript_path.parent.mkdir(parents=True, exist_ok=True)
            stub = FOUNTAIN_STUB if pj.type == "screenplay" else MANUSCRIPT_STUB
            ch.manuscript_path.write_text(
                stub.format(id=ch.id, title=ch.title, brief=rel(ch.brief_path)),
                encoding="utf-8",
            )
            made.append(rel(ch.manuscript_path))

    emit(args, {"created": made}, [f"created {m}" for m in made] or ["nothing to scaffold"])
    return 0


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

UNENFORCEABLE = [
    "Whether a claim is true. The linter checks that a source is cited, not that it says so.",
    "Whether the voice matches the style guide. That is the voice-auditor's job and it is a judgement.",
    "Whether a unit delivers the argument its brief promised.",
    "Whether a seam reads as one work or as two documents stapled together. `seams` extracts the joins; the seam-reviewer judges them.",
    "Whether a figure shows the mechanism its spec describes.",
]


def _record_repeat(repeats, tokens, start, end, shingle_owners) -> None:
    """Store one maximal repeated run, keyed by its text so it reports once."""
    phrase = " ".join(tokens[start:end])
    owners: set[str] = set()
    for i in range(start, max(start + 1, end - SHINGLE + 1)):
        owners |= shingle_owners.get(tuple(tokens[i : i + SHINGLE]), set())
    repeats.setdefault(phrase, set()).update(owners)


def cmd_lint(pj: Project, args) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if pj.manifest.name == "book.toml":
        warnings.append("manifest is the pre-rename book.toml; `git mv book.toml longform.toml` when convenient")

    # -- structure ---------------------------------------------------------
    part_ids = {p.get("id") for p in pj.parts}
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for ch in pj.chapters:
        if ch.id in seen_ids:
            errors.append(f"{ch.id}: duplicate unit id")
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
    for ch in pj.chapters:
        if ch.status != "planned" and not ch.brief_path.exists():
            errors.append(f"{ch.id}: status {ch.status} but no brief at {rel(ch.brief_path)}")
        if ch.rank >= DRAFTED and not ch.manuscript_path.exists():
            errors.append(f"{ch.id}: status {ch.status} but no manuscript at {rel(ch.manuscript_path)}")
        for note in ch.research:
            if not (ROOT / note).exists():
                errors.append(f"{ch.id}: research note {note} does not exist")
        for figure in ch.figures:
            if not (ROOT / figure).exists():
                errors.append(f"{ch.id}: figure spec {figure} does not exist")
            if pj.type in ("audiobook", "screenplay"):
                warnings.append(f"{ch.id}: declares figure {figure} but a {pj.type} cannot show it")

    # -- continuity ordering ----------------------------------------------
    established_by: dict[str, str] = {}
    for ch in pj.chapters:
        for key in ch.requires:
            if key not in established_by:
                errors.append(f"{ch.id}: requires {key!r}, which no earlier unit establishes")
        for key in ch.establishes:
            if key in established_by:
                errors.append(f"{ch.id}: establishes {key!r}, already established by {established_by[key]}")
            else:
                established_by[key] = ch.id

    ledger = ROOT / "continuity.md"
    if ledger.exists():
        ledger_text = ledger.read_text(encoding="utf-8")
        for key, owner in established_by.items():
            if key not in ledger_text:
                warnings.append(f"{owner}: establishes {key!r} but it is not in continuity.md")

    # -- seam reviews ------------------------------------------------------
    # A seam whose two sides changed after its review was written is unreviewed.
    for a, b, path in seam_pairs(pj, "manuscript"):
        report = ROOT / "review" / "seams" / f"{a.id}__{b.id}.review.md"
        if a.rank >= STATUSES.index("reviewed") and b.rank >= STATUSES.index("reviewed"):
            if not report.exists():
                warnings.append(f"seam {a.id}→{b.id}: both sides reviewed but the seam has no review")
            elif report.stat().st_mtime < max(a.manuscript_path.stat().st_mtime, b.manuscript_path.stat().st_mtime):
                warnings.append(f"seam {a.id}→{b.id}: review predates the latest edit to one side")

    # -- drafted prose -----------------------------------------------------
    shingle_owners: dict[tuple[str, ...], set[str]] = defaultdict(set)
    chapter_tokens: dict[str, list[str]] = {}
    for ch in pj.chapters:
        if ch.rank < DRAFTED or not ch.manuscript_path.exists():
            continue
        text = body_of(ch.manuscript_path)

        open_markers = OPEN_MARKERS.findall(text)
        if open_markers:
            where = errors if ch.status in ("reviewed", "final") else warnings
            where.append(
                f"{ch.id}: {len(open_markers)} unresolved marker(s): " + ", ".join(sorted(set(open_markers))[:4])
            )

        heading = next((l for l in text.splitlines() if l.startswith("# ")), None)
        if heading is None:
            errors.append(f"{ch.id}: manuscript has no '# Title' heading")
        elif heading[2:].strip() != ch.title:
            warnings.append(f"{ch.id}: heading {heading[2:].strip()!r} does not match manifest title {ch.title!r}")

        for fig in FIGURE_DIRECTIVE.findall(text):
            spec = ROOT / "graphics" / "specs" / f"{fig}.md"
            if not spec.exists():
                errors.append(f"{ch.id}: renders figure {fig!r} with no spec at {rel(spec)}")

        if ch.word_target:
            words = len(text.split())
            if not ch.word_target * (1 - WORD_TOLERANCE) <= words <= ch.word_target * (1 + WORD_TOLERANCE):
                warnings.append(f"{ch.id}: {words:,} words against a target of {ch.word_target:,}")

        tokens = normalised_words(text)
        chapter_tokens[ch.id] = tokens
        for i in range(len(tokens) - SHINGLE):
            shingle_owners[tuple(tokens[i : i + SHINGLE])].add(ch.id)

    # Overlapping shingles describe one passage, not ten. Merge each unit's
    # consecutive repeated positions into maximal runs and report each distinct
    # passage once, however many units it turns up in.
    repeats: dict[str, set[str]] = {}
    for tokens in chapter_tokens.values():
        start = None
        for i in range(len(tokens) - SHINGLE + 1):
            repeated = len(shingle_owners.get(tuple(tokens[i : i + SHINGLE]), set())) >= SHINGLE_MIN_CHAPTERS
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

    return report_findings(args, errors, warnings, UNENFORCEABLE)


def report_findings(args, errors, warnings, unenforceable=None) -> int:
    if args.strict:
        errors = errors + warnings
        warnings = []
    payload = {"errors": errors, "warnings": warnings}
    if unenforceable:
        payload["unenforceable"] = unenforceable
    lines = [f"warn  {w}" for w in warnings] + [f"ERROR {e}" for e in errors]
    if not errors and not warnings:
        lines.append("clean")
    lines.append(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    emit(args, payload, lines)
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
#
# Writers never read each other, so the joins between units are where an
# agentic manuscript breaks first: the next unit re-introduces what the last
# one just said, opens from a state the last one never left the reader in, or
# both sides recap. `seams` cuts each join out — the tail of unit N, the head of
# unit N+1, and what both briefs said the join should be — into one small file,
# so the seam-reviewer judges a few hundred words instead of reading the work.


def seam_pairs(pj: Project, layer: str):
    present = []
    for ch in pj.chapters:
        path = pj.script_path(ch) if layer == "script" else ch.manuscript_path
        if path.exists():
            present.append((ch, path))
    # Only adjacent units in manifest order form a seam; a gap (undrafted unit)
    # breaks the chain rather than joining non-neighbours.
    order = {ch.id: i for i, ch in enumerate(pj.chapters)}
    for (a, pa), (b, pb) in zip(present, present[1:]):
        if order[b.id] == order[a.id] + 1:
            yield a, b, (pa, pb)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _head(text: str, n: int) -> str:
    out, count = [], 0
    for p in _paragraphs(text):
        out.append(p)
        count += len(p.split())
        if count >= n:
            break
    return "\n\n".join(out)


def _tail(text: str, n: int) -> str:
    out, count = [], 0
    for p in reversed(_paragraphs(text)):
        out.insert(0, p)
        count += len(p.split())
        if count >= n:
            break
    return "\n\n".join(out)


def _brief_section(path: Path, heading: str) -> str:
    if not path.exists():
        return "(no brief)"
    m = re.search(rf"^## {heading}\s*\n(.*?)(?=^## |\Z)", path.read_text(encoding="utf-8"), re.M | re.S)
    if not m:
        return "(brief has no Seams section)"
    text = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()
    return text or "(empty)"


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def cmd_seams(pj: Project, args) -> int:
    outdir = ROOT / "review" / "seams"
    outdir.mkdir(parents=True, exist_ok=True)
    parts = {p.get("id"): p.get("title", "") for p in pj.parts}
    written = []
    for a, b, (pa, pb) in seam_pairs(pj, args.layer):
        ta, tb = body_of(pa), body_of(pb)
        if args.layer == "script" and pj.script_ext == ".ssml":
            ta, tb = _strip_tags(ta), _strip_tags(tb)
        boundary = ""
        if a.part != b.part:
            boundary = f"\n**Part boundary:** {parts.get(a.part, a.part)} → {parts.get(b.part, b.part)}\n"
        doc = f"""# Seam {a.id} → {b.id} ({args.layer})

Type: {pj.type}. {a.title} → {b.title}.
{boundary}
## What the briefs say the join should be

**{a.id} hands off to:**
{_brief_section(a.brief_path, "Seams")}

**{b.id} picks up from:**
{_brief_section(b.brief_path, "Seams")}

## End of {a.id} — {a.title} (last ~{args.words} words, `{rel(pa)}`)

{_tail(ta, args.words)}

## Start of {b.id} — {b.title} (first ~{args.words} words, `{rel(pb)}`)

{_head(tb, args.words)}
"""
        path = outdir / f"{a.id}__{b.id}{'.script' if args.layer == 'script' else ''}.md"
        path.write_text(doc, encoding="utf-8")
        written.append({"seam": f"{a.id}→{b.id}", "file": rel(path), "part_boundary": bool(boundary)})

    lines = [f"wrote {w['file']}" + ("  (part boundary)" if w["part_boundary"] else "") for w in written]
    lines.append(f"{len(written)} seam(s) at layer {args.layer}" if written else "no adjacent drafted pairs yet")
    emit(args, {"layer": args.layer, "seams": written}, lines)
    return 0


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------


def _ordered(pj: Project):
    """Yield (part_or_None, chapter) in manifest order, parts first."""
    by_part: dict[str, list[Chapter]] = defaultdict(list)
    loose: list[Chapter] = []
    for ch in pj.chapters:
        (by_part[ch.part] if ch.part else loose).append(ch)
    for part in pj.parts:
        for i, ch in enumerate(by_part.get(part.get("id", ""), [])):
            yield (part if i == 0 else None), ch
    for ch in loose:
        yield None, ch


def cmd_assemble(pj: Project, args) -> int:
    meta = pj.meta
    out_name = {"screenplay": "screenplay.fountain", "report": "report.md"}.get(pj.type, "manuscript.md")
    out = ROOT / (args.out or f"dist/{out_name}")
    out.parent.mkdir(parents=True, exist_ok=True)

    pieces: list[str] = []
    if pj.type == "screenplay":
        # Fountain title page: key/value lines, then a blank line, then the script.
        pieces.append(f"Title: {meta.get('title', 'Untitled')}")
        if meta.get("author"):
            pieces.append(f"Credit: Written by\nAuthor: {meta['author']}")
        if meta.get("snapshot_date"):
            pieces.append(f"Draft date: {meta['snapshot_date']}")
        pieces.append("")
    elif pj.type == "report":
        # Pandoc title block, read by `export`.
        fm = {"title": meta.get("title", "Untitled")}
        if meta.get("subtitle"):
            fm["subtitle"] = meta["subtitle"]
        if meta.get("author"):
            fm["author"] = meta["author"]
        if meta.get("snapshot_date"):
            fm["date"] = meta["snapshot_date"]
        pieces.append("---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n")
    else:
        pieces.append(f"# {meta.get('title', 'Untitled')}\n")
        if meta.get("subtitle"):
            pieces.append(f"## {meta['subtitle']}\n")
        if meta.get("author"):
            pieces.append(f"*{meta['author']}*\n")
        if meta.get("snapshot_date"):
            pieces.append(f"Content is current as of {meta['snapshot_date']}.\n")

    comment = (lambda s: f"/* {s} */") if pj.type == "screenplay" else (lambda s: f"<!-- {s} -->")
    for part, ch in _ordered(pj):
        if part is not None and pj.type in ("book", "audiobook"):
            pieces.append(f"\n\n# Part — {part.get('title', '')}\n")
        if not ch.manuscript_path.exists():
            pieces.append("\n" + comment(f"{ch.id} {ch.title}: not drafted") + "\n")
            continue
        pieces.append("\n" + body_of(ch.manuscript_path).strip() + "\n")

    out.write_text("\n".join(pieces), encoding="utf-8")

    drafted = [c for c in pj.chapters if c.manuscript_path.exists()]
    words = sum(c.words() for c in drafted)
    sidecar = out.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "type": pj.type,
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "snapshot_date": meta.get("snapshot_date", ""),
                "profile": pj.production.get("profile", ""),
                "handoff": pj.production.get("handoff", ""),
                "words": words,
                "chapters": [{"id": c.id, "title": c.title, "part": c.part, "status": c.status} for c in pj.chapters],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {rel(out)} — {len(drafted)}/{len(pj.chapters)} units, {words:,} words")
    print(f"wrote {rel(sidecar)} — handoff metadata")
    return 0


# ---------------------------------------------------------------------------
# export (report, screenplay)
# ---------------------------------------------------------------------------


def run(cmd: list[str] | str, dry: bool, shell: bool = False) -> int:
    shown = cmd if isinstance(cmd, str) else shlex.join(cmd)
    print(f"$ {shown}", flush=True)
    if dry:
        return 0
    return subprocess.run(cmd, shell=shell, cwd=ROOT).returncode


def cmd_export(pj: Project, args) -> int:
    custom = pj.output.get("export_cmd", "")
    if pj.type == "report":
        src, dst = ROOT / "dist/report.md", ROOT / "dist/report.pdf"
        if not src.exists():
            print("ERROR dist/report.md missing; run assemble first", file=sys.stderr)
            return 1
        if custom:
            return run(custom.format(input=rel(src), output=rel(dst)), args.dry_run, shell=True)
        if not shutil.which("pandoc"):
            print("ERROR pandoc not installed; set [output] export_cmd or install pandoc", file=sys.stderr)
            return 1
        rp = pj.output
        cmd = ["pandoc", rel(src), "-o", rel(dst), "--standalone", "--resource-path", ".:graphics/assets"]
        engine = rp.get("pdf_engine", "typst")
        if engine and shutil.which(engine):
            cmd += [f"--pdf-engine={engine}"]
            if engine == "typst":
                # pandoc's typst template passes an empty font list unless one is set.
                cmd += ["-V", f"mainfont={rp.get('mainfont', 'Libertinus Serif')}"]
        if rp.get("toc", True):
            cmd.append("--toc")
        if rp.get("number_sections", True):
            cmd.append("--number-sections")
        bib = ROOT / rp.get("bibliography", "research/references.bib")
        if bib.exists():
            cmd += ["--citeproc", "--bibliography", rel(bib)]
        return run(cmd, args.dry_run)

    if pj.type == "screenplay":
        src, dst = ROOT / "dist/screenplay.fountain", ROOT / "dist/screenplay.pdf"
        if not src.exists():
            print("ERROR dist/screenplay.fountain missing; run assemble first", file=sys.stderr)
            return 1
        if custom:
            return run(custom.format(input=rel(src), output=rel(dst)), args.dry_run, shell=True)
        for tool, cmd in (
            ("afterwriting", ["afterwriting", "--source", rel(src), "--pdf", rel(dst), "--overwrite"]),
            ("screenplain", ["screenplain", "--format", "pdf", rel(src), rel(dst)]),
        ):
            if shutil.which(tool):
                return run(cmd, args.dry_run)
        print(
            "ERROR no Fountain renderer found (afterwriting, screenplain). Install one, or set\n"
            "      [output] export_cmd = \"<cmd with {input} {output}>\". dist/screenplay.fountain\n"
            "      opens directly in Highland, Fade In, Slugline and WriterDuet.",
            file=sys.stderr,
        )
        return 1

    print(f"export is for report and screenplay; a {pj.type} uses " + (
        "the production handoff" if pj.type == "book" else "script-lint, render and audio-assemble"))
    return 1


# ---------------------------------------------------------------------------
# audiobook: script-lint, render, audio-assemble
# ---------------------------------------------------------------------------
#
# The spoken script (audio/script/) is a third layer after brief and manuscript:
# the manuscript is the text of record; the script is what the TTS engine reads.
# Written forms are normalised to spoken forms here — "2026" to "twenty
# twenty-six", "§4.2" to "section four point two" — because TTS front-ends
# guess, and each guess is made per chapter, so the same figure is read two
# different ways an hour apart.

SPEECH_CHECKS = [
    ("digits", re.compile(r"\d[\d,.:]*"), "numbers left as digits — write them as they should be spoken"),
    ("url", re.compile(r"https?://|www\.|\b[\w.-]+\.(?:com|org|net|io|ai|co)\b"), "URL or domain — say it or drop it"),
    ("email", re.compile(r"\b\S+@\S+\.\w+\b"), "email address"),
    ("markdown", re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|)|\*\*|__|`|\[[^\]]*\]\([^)]*\)", re.M),
     "markdown syntax — headings, bullets, tables, emphasis or links"),
    ("marker", OPEN_MARKERS, "unresolved [VERIFY]/[TK] marker"),
    ("symbol", re.compile(r"[%&/$€£₪@#+=<>~^_→←×÷§°]"), "symbol the engine will read literally or skip"),
    ("brackets", re.compile(r"[()\[\]{}]"), "parenthetical — a listener cannot see brackets; recast as a sentence"),
    ("figure", re.compile(r"\b(?:see|in) (?:figure|table|fig\.)\b|\b(?:above|below)\b", re.I),
     "visual reference (figure, table, above, below)"),
]
ACRONYM = re.compile(r"\b[A-Z]{2,}s?\b")
LONG_SENTENCE = 45  # words; a listener cannot re-read


def lexicon_terms() -> set[str]:
    path = ROOT / "guides" / "pronunciation.md"
    terms: set[str] = set()
    if not path.exists():
        return terms
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*(?:-|Term\b)", line):
            cell = line.strip("|").split("|")[0].strip()
            if cell:
                terms.add(cell)
    return terms


def cmd_script_lint(pj: Project, args) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    if pj.type != "audiobook":
        warnings.append(f"[output] type is {pj.type!r}; script-lint is for audiobooks")
    lexicon = lexicon_terms()
    unknown_acronyms: Counter = Counter()

    for ch in pj.chapters:
        script = pj.script_path(ch)
        if not script.exists():
            if ch.rank >= DRAFTED:
                errors.append(f"{ch.id}: drafted but no spoken script at {rel(script)}")
            continue
        raw = script.read_text(encoding="utf-8")
        if pj.script_ext == ".ssml":
            try:
                ET.fromstring(raw if raw.lstrip().startswith("<speak") else f"<speak>{raw}</speak>")
            except ET.ParseError as exc:
                errors.append(f"{ch.id}: SSML is not well-formed: {exc}")
            text = _strip_tags(raw)
        else:
            text = raw
        if ch.manuscript_path.exists() and script.stat().st_mtime < ch.manuscript_path.stat().st_mtime:
            warnings.append(f"{ch.id}: script is older than the manuscript — re-adapt before rendering")
        for name, rx, what in SPEECH_CHECKS:
            hits = rx.findall(text)
            if hits:
                sample = ", ".join(repr(h if isinstance(h, str) else h[0]) for h in list(dict.fromkeys(hits))[:4])
                (errors if name in ("marker", "markdown") else warnings).append(
                    f"{ch.id}: {len(hits)}× {what}: {sample}"
                )
        for ac in ACRONYM.findall(text):
            if ac.rstrip("s") not in lexicon and ac not in lexicon:
                unknown_acronyms[ac] += 1
        long = [s for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > LONG_SENTENCE]
        if long:
            warnings.append(f"{ch.id}: {len(long)} sentence(s) over {LONG_SENTENCE} words")

    if unknown_acronyms:
        top = ", ".join(f"{a}×{n}" for a, n in unknown_acronyms.most_common(12))
        warnings.append(f"acronyms not in guides/pronunciation.md (engines guess, inconsistently): {top}")
    return report_findings(args, errors, warnings)


def cmd_render(pj: Project, args) -> int:
    template = pj.audio.get("render_cmd", "")
    if not template:
        print(
            "ERROR [audio] render_cmd is empty. Set it to a shell command that turns one script\n"
            "      file into one audio file, using {input} {output} {id} {title} {voice}.",
            file=sys.stderr,
        )
        return 1
    targets = [c for c in pj.chapters if not args.only or c.id in args.only]
    failed, done, skipped = [], [], []
    for ch in targets:
        src, dst = pj.script_path(ch), pj.audio_path(ch)
        if not src.exists():
            skipped.append(f"{ch.id} (no script)")
            continue
        if dst.exists() and dst.stat().st_size and not args.force:
            if dst.stat().st_mtime < src.stat().st_mtime:
                print(f"warn  {ch.id}: rendered audio is older than its script; --force --only {ch.id} to redo")
            skipped.append(f"{ch.id} (rendered)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = template.format(
            input=shlex.quote(rel(src)), output=shlex.quote(rel(dst)), id=ch.id,
            title=shlex.quote(ch.title), voice=shlex.quote(pj.audio.get("voice", "")),
        )
        rc = run(cmd, args.dry_run, shell=True)
        if args.dry_run:
            continue
        if rc != 0 or not dst.exists() or not dst.stat().st_size:
            failed.append(ch.id)
            dst.unlink(missing_ok=True)  # never leave a partial file that a resume would trust
            print(f"ERROR {ch.id}: render failed (exit {rc})")
            if not args.keep_going:
                break
        else:
            done.append(ch.id)
    print(f"\nrendered {len(done)}, skipped {len(skipped)}, failed {len(failed)}")
    for s in skipped:
        print(f"  skip {s}")
    return 1 if failed else 0


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _ffmeta_escape(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def cmd_audio_assemble(pj: Project, args) -> int:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"ERROR {tool} not installed", file=sys.stderr)
            return 1
    a, meta = pj.audio, pj.meta
    rate, channels = int(a.get("sample_rate", 44100)), int(a.get("channels", 1))
    gap = float(a.get("gap_seconds", 2.0))
    fmt = a.get("chapter_title_format", "{n}. {title}")

    missing = [c.id for c in pj.chapters if not pj.audio_path(c).exists()]
    if missing and not args.allow_missing:
        print(f"ERROR not rendered: {', '.join(missing)} (render them, or --allow-missing)", file=sys.stderr)
        return 1

    # (label, source path) in play order; intro/outro are optional bumpers.
    pieces: list[tuple[str, Path]] = []
    if a.get("intro"):
        pieces.append(("Opening", ROOT / a["intro"]))
    n = 0
    for ch in pj.chapters:
        p = pj.audio_path(ch)
        if p.exists():
            n += 1
            pieces.append((fmt.format(n=n, id=ch.id, title=ch.title), p))
    if a.get("outro"):
        pieces.append(("Closing", ROOT / a["outro"]))

    container = a.get("container", "m4b")
    out = ROOT / "dist" / f"audiobook.{container}"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        for label, p in pieces:
            print(f"  {label:<50} {rel(p)}")
        print(f"would write {rel(out)}")
        return 0

    with tempfile.TemporaryDirectory(prefix="longform-audio-") as tmpd:
        tmp = Path(tmpd)
        pcm = ["-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le"]
        silence = tmp / "gap.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={rate}:cl={'mono' if channels == 1 else 'stereo'}",
             "-t", str(gap), *pcm, str(silence)], check=True,
        )
        concat_lines, chapters_meta, t = [], [], 0.0
        gap_len = ffprobe_duration(silence) if gap > 0 else 0.0
        for i, (label, src) in enumerate(pieces):
            wav = tmp / f"{i:03d}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *pcm, str(wav)], check=True)
            dur = ffprobe_duration(wav)
            chapters_meta.append({"title": label, "file": rel(src), "start": round(t, 3), "end": round(t + dur, 3)})
            concat_lines.append(f"file '{wav}'")
            t += dur
            if gap > 0 and i < len(pieces) - 1:
                concat_lines.append(f"file '{silence}'")
                t += gap_len
        joined = tmp / "joined.wav"
        (tmp / "list.txt").write_text("\n".join(concat_lines) + "\n")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy", str(joined)],
            check=True,
        )

        # Chapter marks and tags travel in an ffmetadata file.
        tags = {
            "title": meta.get("title", ""),
            "album": meta.get("title", ""),
            "artist": meta.get("author", ""),
            "album_artist": meta.get("author", ""),
            "composer": a.get("narrator", ""),
            "genre": a.get("genre", "Audiobook"),
            "date": meta.get("snapshot_date", "")[:4],
            "comment": meta.get("subtitle", ""),
        }
        ffmeta = [";FFMETADATA1"] + [f"{k}={_ffmeta_escape(v)}" for k, v in tags.items() if v]
        for c in chapters_meta:
            ffmeta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}",
                       f"END={int(c['end'] * 1000)}", f"title={_ffmeta_escape(c['title'])}"]
        meta_file = tmp / "chapters.ffmeta"
        meta_file.write_text("\n".join(ffmeta) + "\n", encoding="utf-8")
        (ROOT / "dist" / "chapters.ffmeta").write_text(meta_file.read_text(encoding="utf-8"), encoding="utf-8")

        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(meta_file)]
        cover = ROOT / a["cover"] if a.get("cover") else None
        if cover and cover.exists():
            cmd += ["-i", str(cover)]
        cmd += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
        if cover and cover.exists():
            cmd += ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        if a.get("loudness_lufs") not in (None, ""):
            cmd += ["-af", f"loudnorm=I={a['loudness_lufs']}:TP=-3:LRA=11"]
        cmd += ["-c:a", "aac", "-b:a", a.get("bitrate", "64k" if channels == 1 else "128k"),
                "-ar", str(rate)]
        if container in ("m4b", "m4a"):
            cmd += ["-movflags", "+faststart", "-f", "mp4"]
        cmd.append(str(out))
        subprocess.run(cmd, check=True)

    total = ffprobe_duration(out)
    sidecar = ROOT / "dist" / "audiobook.json"
    sidecar.write_text(
        json.dumps(
            {
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "narrator": a.get("narrator", ""),
                "voice": a.get("voice", ""),
                "render_cmd": a.get("render_cmd", ""),
                "snapshot_date": meta.get("snapshot_date", ""),
                "file": rel(out),
                "duration_seconds": round(total, 1),
                "md5": hashlib.md5(out.read_bytes()).hexdigest(),
                "missing_chapters": missing,
                "chapters": chapters_meta,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {rel(out)} — {len(chapters_meta)} chapter marks, {total / 3600:.2f} h")
    print(f"wrote {rel(sidecar)} and dist/chapters.ffmeta")
    if missing:
        print(f"warn  assembled without: {', '.join(missing)}")
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

    p = sub.add_parser("seams", help="cut each join between adjacent units into review/seams/")
    p.add_argument("--layer", choices=["manuscript", "script"], default="manuscript")
    p.add_argument("--words", type=int, default=SEAM_WORDS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_seams)

    p = sub.add_parser("assemble", help="concatenate drafted units into dist/")
    p.add_argument("--out", default="")
    p.set_defaults(func=cmd_assemble)

    p = sub.add_parser("export", help="report -> PDF (pandoc/typst); screenplay -> PDF (Fountain renderer)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("script-lint", help="audiobook: check spoken scripts for unspeakable text")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd_script_lint)

    p = sub.add_parser("render", help="audiobook: run [audio] render_cmd once per chapter, resumably")
    p.add_argument("--only", nargs="*", default=[])
    p.add_argument("--force", action="store_true", help="re-render even if the audio exists")
    p.add_argument("--keep-going", action="store_true", help="continue past a failed chapter")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("audio-assemble", help="audiobook: join chapters, chapter marks, tags, loudness -> dist/")
    p.add_argument("--allow-missing", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_audio_assemble)

    args = parser.parse_args()
    try:
        pj = load()
    except (ManifestError, tomllib.TOMLDecodeError, TypeError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    return args.func(pj, args)


if __name__ == "__main__":
    sys.exit(main())
