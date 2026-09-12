# Figures

The `paper/` subdirectory contains the unchanged reference-workflow asset
reused from SIDERIUS-Paper. Its provenance and conversion command are recorded
in [`paper/README.md`](paper/README.md); the PDF is the byte-identical source
and the PNG is a local faithful preview.

The maintained diagrams are committed assets referenced from Markdown. Existing
SVG figures remain in place; the Paper reference figure is an unchanged PDF
with a generated PNG preview:

```markdown
![alt text](../assets/discovery-loop.svg)     <!-- from a page under docs/ -->
![alt text](docs/assets/discovery-loop.svg)   <!-- from README.md at the root -->
```

## Why the existing SVG figures are retained

Mermaid renders as generic auto-laid-out boxes; it cannot express a deliberate
composition — emphasis, grouping, a dashed "not yet real" panel, a takeaway line.
GitHub also strips `<style>` and positioned `<div>`s from Markdown, so an HTML
figure cannot be embedded directly. SVG has native absolute positioning, renders
everywhere GitHub renders images, stays crisp at any scale, and diffs as text.

## Conventions

Keep these consistent so the figures read as one system.

| element | rule |
|---|---|
| canvas | 960 px wide; height to fit. Scales down cleanly in a README column |
| background | **an explicit white `<rect>` is required** — without it, dark text is invisible on GitHub's dark theme |
| font | `'Helvetica Neue', Helvetica, Arial, sans-serif` |
| node labels | 13.5 px bold, white on a filled `rx="10"` chip |
| role subtitles | 10.5 px italic, white at 0.9 opacity |
| captions | 12 px, `#5D6D7E` |
| takeaway line | 15 px bold italic, `#C0392B`, centred at the bottom — one sentence, the thing to remember |
| "not yet real" | dashed stroke, `stroke-dasharray="6,5"` |

Palette: `#2980B9` blue · `#8E44AD` purple · `#F39C12` amber · `#16A085` teal ·
`#2C3E50` navy · `#E74C3C` red · `#E67E22` orange · `#7F8C8D` / `#95A5A6` grey ·
`#FBFCFC` panel fill · `#D5DBDB` panel border.

## Two traps, both hit while authoring these

1. **A CSS class in `<style>` beats a presentation attribute.** `class="h"`
   setting `fill:#fff` overrides `fill="#6C3483"` on the same element. Use an
   inline `style="..."` attribute to override, or a dedicated class.
2. **`<tspan>` inside a `text-anchor="middle"` element can be dropped** by some
   renderers. For centred text, use separate `<text>` lines rather than tspans.

## Checking a change

For the Paper asset's exact conversion command, tool version, and hashes, see
[`paper/README.md`](paper/README.md). Do not edit the source Paper checkout.

## Current figures

| file | used by |
|---|---|
| `discovery-loop.svg` | `README.md`, `docs/concepts/overview.md` |
| `ownership-split.svg` | `README.md`, `docs/concepts/overview.md` |
| `three-kinds-of-number.svg` | `README.md`, `docs/concepts/objectives-and-metrics.md` |
