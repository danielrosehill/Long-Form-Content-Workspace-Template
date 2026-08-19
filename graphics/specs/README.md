# Figure specs

One file per figure, named `<id>.md`, where `<id>` is what the manuscript
references with `::: figure <id>`.

A spec is the contract handed to the figure-maker. It states what the figure must
show, every label verbatim, and where its facts come from — so the figure can be
checked against something rather than admired.

## Template

```markdown
# <id> — <caption>

**Kind:** diagram | plate | screenshot
**Appears in:** ch0n
**Source of truth:** <file, measurement or document the figure depicts>

## Must show

<!-- The mechanism, in words. If this cannot be written, the figure has no job. -->

## Must not imply

<!-- The wrong reading the figure could invite. -->

## Labels

<!-- Every string that appears in the figure, verbatim. Figure-makers invent
     plausible labels when not given exact ones, and invented labels print. -->

## Caption

<!-- The caption as it appears under the figure. -->
```
