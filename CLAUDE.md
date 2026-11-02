# Working in this long-form content workspace

Directives for any agent operating in this repository. The reasoning behind them
is in [Agentic-Long-Form-Content](https://github.com/danielrosehill/Agentic-Long-Form-Content);
this is what to *do*.

## What this workspace makes

One work, of the type set in `[output] type` in `longform.toml`:

| Type | Unit of delegation | Ends as |
| --- | --- | --- |
| `book` | chapter | `dist/manuscript.md` → print-geometry handoff |
| `report` | section | `dist/report.pdf` (pandoc + typst) |
| `screenplay` | sequence (a run of scenes one writer owns), Fountain | `dist/screenplay.fountain` / `.pdf` |
| `audiobook` | chapter | `dist/audiobook.m4b`, chaptered and tagged |

Definition, planning, drafting and review are identical for all four. Only the
production stage branches. "Chapter" below means the unit, whatever the type.

## The constraint everything here answers to

A long work does not fit in one agent's attention, and quality degrades long
before the context window fills. Every rule below exists to keep each agent's
working set small enough that it never reaches the part of the window where it
starts producing plausible filler.

The expensive resource being managed is **not tokens, it is attention**. An agent
that has read nine chapters to write the tenth will write a worse tenth chapter
than one that read a two-page brief.

## Source-of-truth documents

Nothing else defines the work. If you find another document describing
structure, voice or scope, it is drift — fold it into one of these and delete it.

| Document | Owns | Read by |
| --- | --- | --- |
| `longform.toml` | Type, structure, status, targets, continuity keys, audio settings | every script and agent |
| `spec/spec.md` | What the work is, who it is for, what it must not become | planning, review |
| `guides/style-guide.md` | Voice, register, conventions (and the spoken rules for an audiobook) | every writing and review agent |
| `guides/graphics-style-guide.md` | Visual language (book, report) | every graphics agent |
| `guides/pronunciation.md` | How names, acronyms and figures are said (audiobook) | narration adapters, script-lint |
| `outline/outline.md` + `outline/briefs/` | The plan and the per-unit contracts | planning, writing |

**The outline never ships.** Nothing in `outline/` appears in `dist/`.

## What each agent may read

This is the whole architecture. Violating it is how agent-written long-form work
comes out repetitive and tonally inconsistent.

| Agent | Reads | Never reads |
| --- | --- | --- |
| Chapter writer | Its own brief, the style guide, its research notes, the ledger | Other chapters' drafts |
| Researcher | The brief it was given, external sources | Drafts |
| Proofreader | One chapter, the style guide | The rest of the work |
| Voice auditor | Samples across chapters, the style guide | Full drafts of everything |
| Continuity auditor | `lint --json`, chapter summaries, the continuity ledger | Full drafts of everything |
| Seam reviewer | One `review/seams/<a>__<b>.md` file | Anything else in `manuscript/` |
| Narration adapter | One chapter's manuscript, style guide, pronunciation lexicon | Other chapters |
| Publication | `dist/`, the profile or `[audio]` | Briefs, research |

A writer that reads the previous chapter will *echo* it — restating its setup,
borrowing its examples, repeating its transitions. Cross-chapter consistency is
bought with the brief and the continuity ledger, not with reading.

## Seams

The price of writers who never read each other is paid at the joins. A seam is
where chapter N ends and N+1 begins, and it is where this kind of work breaks
most: N+1 re-introduces what N just said, both sides recap or preview, N+1 opens
from a state N never left the reader in, or the register jumps.

- Every brief has a **Seams** section: what it picks up from, what it hands off
  to. The outline-architect writes both sides of every join.
- `python3 scripts/longform.py seams` cuts each join into
  `review/seams/<a>__<b>.md`. One `seam-reviewer` per file, in parallel.
- Findings go to `review/seams/<a>__<b>.review.md`, addressed to one side or to
  the outline. Fixes are made by the chapter's writer, at the edge only.
- `lint` warns when both sides of a seam are `reviewed` but the seam has no
  review, or when the review predates an edit to either side.
- Audiobooks get a second seam pass on the spoken scripts
  (`seams --layer script`), because adaptation adds openings and closings.

## Parallelism

Chapter writers run in parallel. This is safe when, and only when, two chapters
do not draw on the same source material for the same purpose. Two agents given
the same source will describe it differently and both descriptions will ship.

Before dispatching a batch, check `research` and `establishes` in
`longform.toml`. Chapters that share a research note or establish related keys
go in **different batches**, sequentially.

Writers never write outside `manuscript/<their chapter>`. Reviewers never edit
prose; they write findings and the writer applies them.

## Continuity

`continuity.md` is the ledger: every term, figure, claim, character, location
and timeline fact the work has established, with the chapter that established
it. It is the only mechanism by which chapter 12 knows what chapter 3 said.

- A chapter may only `require` a key an **earlier** chapter `establishes`.
  `lint` enforces the ordering.
- When a writer establishes something, it goes in the ledger in the same turn.

## Facts

- A writer that needs a fact it cannot reach leaves `[VERIFY: what is needed]`.
  It does not guess and does not soften the claim to something safe.
- `lint` treats markers as warnings while drafting and **errors** once a chapter
  is `reviewed` or `final`. `script-lint` treats them as errors always: a
  marker read aloud ships.
- `snapshot_date` is the date the content is true as of.

## Commands

```bash
python3 scripts/longform.py status              # what is drafted, what is not
python3 scripts/longform.py scaffold            # stub briefs and manuscripts
python3 scripts/longform.py lint [--strict]     # mechanical gates
python3 scripts/longform.py seams [--layer script]   # cut joins for the seam reviewers
python3 scripts/longform.py assemble            # concatenate to dist/
python3 scripts/longform.py export              # report / screenplay → PDF
python3 scripts/longform.py script-lint         # audiobook: unspeakable text
python3 scripts/longform.py render [--only ch03]     # audiobook: TTS per chapter, resumable
python3 scripts/longform.py audio-assemble      # audiobook: join, marks, tags, loudness
```

Output goes to `dist/`, never `build/` — a global gitignore excludes `build/`.

## What lint cannot do

It checks that a source is cited, not that the source says what the chapter
claims. It cannot tell whether a chapter delivered its brief's argument, hear
voice drift, or judge whether a seam reads as one work. Read the work yourself.
A clean lint means the mechanical failures are absent, not that the work is good.

## Production boundary

This repository owns the text: structure, figures, assembly, and for an
audiobook the spoken script, rendering and the finished file.

- **book:** print geometry (trim, gutter, spine, cover wrap, pre-flight) belongs
  to the plugin in `[production] handoff`, default `kdp-publishing`. Do not
  reimplement it. `assemble` writes `dist/manuscript.json` for it.
- **audiobook:** the TTS engine is whatever `[audio] render_cmd` calls. The
  workspace does not know or care which; it passes one script file in and
  expects one audio file out.
