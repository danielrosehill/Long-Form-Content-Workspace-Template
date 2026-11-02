# <Title>

> Replace this README when the workspace is instantiated. It is the project's
> status page — what the work is, where it is up to, how to build it.

**Type:** book | report | screenplay | audiobook · **Status:** intake · **Target:** 45,000 words

## What this is

<!-- Two paragraphs. What did not exist before this work, and who needed it. -->

## Where it is up to

```bash
python3 scripts/longform.py status
```

## Layout

| Path | What lives there |
| --- | --- |
| `longform.toml` | Type, structure, status, continuity keys, audio settings — the single source of truth |
| `spec/` | The brief as given, the interview that filled its gaps, the settled spec |
| `guides/` | Style guide, graphics style guide, pronunciation lexicon — binding on every agent |
| `outline/` | The plan and per-unit briefs. **Never ships.** |
| `manuscript/` | Drafted units, one file each (`.md`, or `.fountain` for a screenplay) |
| `research/` | Research notes and the source register |
| `graphics/` | Figure specs, generated assets, diagram sources |
| `review/` | Findings from the review team; `review/seams/` for the joins |
| `audio/script/` | Audiobook: spoken script per chapter (committed) |
| `audio/chapters/` | Audiobook: rendered audio per chapter (not committed) |
| `typeset/` | Body typesetting profiles (book) |
| `dist/` | Assembled output and handoff metadata |

## Building

```bash
python3 scripts/longform.py lint --strict
python3 scripts/longform.py assemble
# report / screenplay
python3 scripts/longform.py export
# audiobook
python3 scripts/longform.py script-lint --strict
python3 scripts/longform.py render
python3 scripts/longform.py audio-assemble
```

A book's print geometry is not built here: `dist/manuscript.json` hands off to
the plugin named in `[production] handoff`.

## How this was made

Written with the [long-form-content](https://github.com/danielrosehill/Long-Form-Content-Plugin)
Claude Code plugin, from the
[Long-Form-Content-Workspace-Template](https://github.com/danielrosehill/Long-Form-Content-Workspace-Template).
The pattern is documented at
[Agentic-Long-Form-Content](https://github.com/danielrosehill/Agentic-Long-Form-Content).
