# <Book title>

> Replace this README when the workspace is instantiated. It is the project's
> status page — what the book is, where it is up to, how to build it.

**Status:** intake · **Target:** 45,000 words · **Channel:** Lulu

## What this book is

<!-- Two paragraphs. What did not exist before this book, and who needed it. -->

## Where it is up to

```bash
python3 scripts/book.py status
```

## Layout

| Path | What lives there |
| --- | --- |
| `book.toml` | Structure, status, continuity keys — the single source of truth |
| `spec/` | The brief as given, the interview that filled its gaps, the settled spec |
| `guides/` | Prose style guide and graphics style guide — binding on every agent |
| `outline/` | The plan and per-chapter briefs. **Never ships.** |
| `manuscript/` | Drafted chapters, one file each |
| `research/` | Research notes and the source register |
| `graphics/` | Figure specs, generated assets, diagram sources |
| `review/` | Findings from the review team |
| `typeset/` | Body typesetting profiles and templates |
| `dist/` | Assembled manuscript and production handoff metadata |

## Building

```bash
python3 scripts/book.py lint --strict
python3 scripts/book.py assemble
```

Print geometry is not built here. `dist/manuscript.json` hands off to the
plugin named in `[production] handoff`.

## How this was made

Written with the [book-writing](https://github.com/danielrosehill/Claude-Book-Writing-Plugin)
Claude Code plugin, from the
[Claude-Book-Workspace-Template](https://github.com/danielrosehill/Claude-Book-Workspace-Template).
The pattern is documented at
[Agentic-Book-Writing](https://github.com/danielrosehill/Agentic-Book-Writing).
