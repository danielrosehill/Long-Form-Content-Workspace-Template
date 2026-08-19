# Working in this book workspace

Directives for any agent operating in this repository. The reasoning behind them
is in [Agentic-Book-Writing](https://github.com/danielrosehill/Agentic-Book-Writing);
this is what to *do*.

## The constraint everything here answers to

A book does not fit in a context window, and quality degrades long before the
window fills. Every rule below exists to keep each agent's working set small
enough that it never reaches the part of the window where it starts producing
plausible filler.

That means the expensive resource being managed is **not tokens, it is
attention**. An agent that has read nine chapters to write the tenth will write
a worse tenth chapter than one that read a two-page brief.

## Source-of-truth documents

Five, and only five. Nothing else defines the book. If you find a sixth document
describing structure, voice or scope, it is drift — fold it into one of these and
delete it.

| Document | Owns | Read by |
| --- | --- | --- |
| `book.toml` | Structure, status, targets, continuity keys | every script and agent |
| `spec/spec.md` | What the book is, who it is for, what it must not become | planning, review |
| `guides/style-guide.md` | Prose voice, register, conventions | every writing and review agent |
| `guides/graphics-style-guide.md` | Visual language | every graphics agent |
| `outline/outline.md` + `outline/briefs/` | The plan and the per-chapter contracts | planning, writing |

**The outline never ships.** It is scaffolding for the agents and for a human
co-author. It is not a chapter, not an appendix, and not a preface. Nothing in
`outline/` appears in `dist/`.

## What each agent may read

This is the whole architecture. Violating it is how books written by agents come
out repetitive and tonally inconsistent.

| Agent | Reads | Never reads |
| --- | --- | --- |
| Chapter writer | Its own brief, the style guide, its research notes, the neighbour summaries in the outline | Other chapters' drafts |
| Researcher | The brief it was given, external sources | Drafts |
| Proofreader | One chapter, the style guide | The rest of the book |
| Voice auditor | Samples across chapters, the style guide | Full drafts of everything |
| Continuity auditor | `lint --json`, chapter summaries, the continuity ledger | Full drafts of everything |
| Publication | `dist/`, the profile | Briefs, research |

A chapter writer that reads the previous chapter will *echo* it — restating its
setup, borrowing its examples, repeating its transitions. Cross-chapter
consistency is bought with the brief and the continuity ledger, not with reading.

## Parallelism

Chapter writers run in parallel. This is safe when, and only when, two chapters
do not draw on the same source material for the same purpose. Two agents given
the same source will describe it differently and both descriptions will ship.

Before dispatching a batch, check the `research` and `establishes` fields in
`book.toml`. Chapters that share a research note or establish related keys go in
**different batches**, sequentially.

Writers never write outside `manuscript/<their chapter>.md`. Reviewers never
edit prose; they write findings to `review/reports/` and the writer applies them.

## Continuity

`continuity.md` is the ledger: every term, figure and claim the book has
established, with the chapter that established it. It is the only mechanism by
which chapter 12 knows what chapter 3 already said.

- A chapter may only `require` a key that an **earlier** chapter `establishes`.
  `book.py lint` enforces the ordering.
- When a writer defines a term, it goes in the ledger in the same turn. A term
  defined in prose but absent from the ledger will be defined again later.

## Facts

Reference works are read for their facts and are worthless when the facts are
wrong.

- A writer that needs a fact it cannot reach leaves `[VERIFY: what is needed]`.
  It does not guess and it does not soften the claim to something safe.
- `lint` treats those markers as warnings while drafting and as **errors** once a
  chapter is `reviewed` or `final`.
- `snapshot_date` in `book.toml` is the date the content is true as of. Print is
  not editable. Say so in the colophon.

## Commands

```bash
python3 scripts/book.py status              # what is drafted, what is not
python3 scripts/book.py status --json       # same, machine-readable
python3 scripts/book.py scaffold            # stub briefs and manuscripts from the manifest
python3 scripts/book.py lint                # mechanical gates
python3 scripts/book.py lint --strict       # warnings become errors; run before production
python3 scripts/book.py assemble            # concatenate to dist/manuscript.md + .json
```

Output goes to `dist/`, never `build/` — a global gitignore excludes `build/`.

## What lint cannot do

It checks that a source is cited, not that the source says what the chapter
claims. It checks that a figure has a spec, not that the figure shows what the
spec describes. It cannot tell whether a chapter delivered the argument its brief
promised, and it cannot hear voice drift.

Read the drafted chapters yourself. A clean lint means the mechanical failures
are absent, not that the book is good.

## Production boundary

This repository owns the manuscript: text, structure, figures, assembly.

It does **not** own print geometry. Trim, gutter, spine width, cover wrap and
pre-flight belong to the plugin named in `[production] handoff` — by default
`kdp-publishing`, which builds the cover last from the interior's measured
extent. Do not reimplement any of that here. `assemble` writes
`dist/manuscript.json` for it to consume.
