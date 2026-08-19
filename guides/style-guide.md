# Style guide

> Binding on every writing and review agent. Read in full before drafting.
>
> A style guide for human writers can be aspirational. This one cannot — it is
> the *only* thing keeping a dozen independently-written chapters sounding like
> one book. Prefer rules an auditor can check over adjectives it cannot.

## Voice

- **Person:** <first / second / third>
- **Tense:** <present / past>
- **Register:** <e.g. "a colleague explaining something at a whiteboard" —
  name a concrete register, not "professional">
- **Contractions:** <yes / no>
- **The reader is addressed as:** <"you" / not addressed>

## Sentences

- Plain declaratives. A sentence that needs to be read twice gets rewritten.
- Vary length deliberately; a run of same-length sentences reads as generated.
- No throat-clearing. Delete "It is important to note that", "In this chapter we
  will", "As we have seen".

## Structure

- Every chapter opens by stating the problem it solves, not by previewing itself.
- Sections are titled with what they say, not what they are about.
  "Spine width is derived, not chosen" over "About spine width".
- Chapters end where the argument ends. No summary section restating the chapter.

## Banned constructions

These are the tells of unedited generated prose. An auditor greps for them.

- "delve", "leverage" (as a verb), "utilise", "seamless", "robust", "landscape"
- "It's worth noting", "That said", "At its core", "In today's world"
- Rule-of-three lists used for rhythm rather than because there are three things
- Sentences beginning "Whether you're a X or a Y"
- Em-dash pairs used more than once per page

## Evidence

- Claims about how something behaves are grounded in something checkable: a
  command run, a document cited, a measurement taken.
- Numbers carry their date when they will decay.
- If the source is unreachable, `[VERIFY: what is needed]` — never a hedge.

## Terminology

Fixed terms, decided once, used everywhere. Add rows as the book establishes them.

| Use | Not |
| --- | --- |
| | |

## Code and commands

- Copied from something that ran, never retyped from memory.
- Elisions marked explicitly.
- Line length capped at <n> characters so it does not wrap in the printed
  measure. This is a measurement of the trim, not a convention — re-derive it if
  the trim or the monospace size changes.

## Figures

- A figure earns its place by showing a mechanism prose would take a page to
  describe. Decorative illustration is out.
- Referenced from prose with `::: figure <id>`, spec at `graphics/specs/<id>.md`.
