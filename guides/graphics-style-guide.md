# Graphics style guide

> Binding on every graphics agent. The point is that thirty figures drawn in
> thirty separate agent invocations look like one book's figures.

## What a figure is for

To show a mechanism, a relationship or a sequence that prose would take a page to
describe and still leave ambiguous. If prose does it in two sentences, prose wins.

Decorative images, stock photography and "visual interest" are out. Every figure
is referenced from the text at the point it is needed.

## Kinds

| Kind | Use | Made with |
| --- | --- | --- |
| Diagram | Structure, flow, relationship | Typst or SVG, authored — not generated |
| Plate | Photograph of a real thing | Camera or existing photography |
| Table | Comparable values across cases | Markdown in the manuscript |
| Screenshot | Interface state that must be recognised | Captured, cropped, annotated |

**Diagrams are authored, not generated.** A generated diagram carries invented
labels and near-miss arrows and neither survives print scrutiny.

## Visual language

- **Palette:** <name 3–4 values, with hex, and what each means>
- **Ink:** single weight for structure, one accent for emphasis. No gradients.
- **Type in figures:** the body serif for labels, the mono for identifiers.
  Never a third family.
- **Line weight:** <pt> for structure, <pt> for detail.
- **Arrowheads:** one style throughout. Direction always means the same thing.
- **Fill:** unfilled shapes by default; fill only where it distinguishes a class.

## Print constraints

- **Colour:** <colour / greyscale>. If the interior is greyscale, every figure
  must survive conversion — no distinction carried by hue alone.
- **Resolution:** raster assets at 300 DPI at final placed size. Compute width
  from the file's pixel dimensions; never set it by hand.
- **Minimum type size in a figure:** 7pt at final size. Smaller does not print.
- **Bleed:** figures sit inside the text block unless a spec says full-bleed.

## Specs

One file per figure at `graphics/specs/<id>.md`, stating what the figure must
show, what it must not imply, every label verbatim, and its source of truth.
The figure-maker works from the spec; the chapter references the id.
