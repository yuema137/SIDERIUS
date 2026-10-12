# Paper figure provenance

## Current Figure 1 and Figure 2

Source: https://zenodo.org/records/23071121
DOI: 10.5281/zenodo.23071121
Title: Beyond a Better Score: Long-Horizon Agentic ML Development and Evaluation Protocol for Physics Time Series.
Export date: 2026-10-08 UTC.

The record's PDF was downloaded unchanged. Its SHA-256 is:

```text
bcc6d6605269725c32d75438712cde697813247bbf4e913ad88f8439de8cd9dc
```

Figure 1 is on PDF page 3, Figure 2 on page 5 (one-based). Crop boxes below
use PDF points and bottom-left coordinates `(left, bottom, right, top)`:

| Figure | Page index (zero-based) | Crop box |
| --- | --- | --- |
| 1 | 2 | (108, 174, 504, 402) |
| 2 | 4 | (108, 542, 504, 710) |

The crops omit surrounding paper prose and captions, retaining all diagram
labels and graphical elements. They replace the older 950-pixel audit previews
previously copied from paper revision `8ef64a181e5b8e606ff6bdb88433c4ecdd7ab31f`.
No scientific content is redrawn. The checked-in SVGs use path outlines for
fonts, a white background, and explicit 1200-pixel display width; there are no
script, external-image, or network dependencies. PNGs provide a raster fallback.

## Export procedure

Use this checkout's frozen environment (pypdfium2) and Poppler's `pdftoppm`
and `pdftocairo`. Save the record's PDF to an external path, represented below
as `/path/to/paper.pdf`. Temporary cropped PDFs are export intermediates and
are not repository assets.

```python
from pathlib import Path
import pypdfium2 as pdfium

source = pdfium.PdfDocument("/path/to/paper.pdf")
for number, index, box in [
    (1, 2, (108, 174, 504, 402)),
    (2, 4, (108, 542, 504, 710)),
]:
    output = pdfium.PdfDocument.new()
    output.import_pages(source, [index])
    page = output[0]
    page.set_cropbox(*box)
    page.set_mediabox(*box)
    output.save(f"/tmp/figure{number}.pdf")
    page.close()
    output.close()
source.close()
```

```bash
for number in 1 2; do
  pdftoppm -cropbox -singlefile -scale-to-x 3200 -scale-to-y -1 -png \
    "/tmp/figure${number}.pdf" "docs/assets/paper/figure${number}"
  pdftocairo -svg "/tmp/figure${number}.pdf" "docs/assets/paper/figure${number}.svg"
done
```

For the SVG display, keep its `viewBox` unchanged. Set root width to `1200`
and height to `691` (Figure 1) or `509` (Figure 2); add a white rectangle
immediately after `</defs>`, covering `(0, 0, 396, 228)` or `(0, 0, 396, 168)`
respectively. This gives predictable display size and contrast on dark pages
without changing the diagram.

## Current export checksums

```text
60ca0079fe0d8699dee10756829e6a66a80dcc39f799a7909781d69cdc02b579  figure1.svg
d6f05c72cc95406550019c9691d5b9a304e92ad086c6bf2b10d986632c3c77a7  figure1.png
aebd73e442dd48eadc98052f3dd16928b2a6d292a33642fa30b91267f1ad8754  figure2.svg
c830f9199587217df4a632c18fbfa5c4b36797b9c66980a4920aa9ce1419eb6d  figure2.png
```

## Earlier illustrations

The retained legacy PNGs came from `yuema137/SIDERIUS-Paper`, revision
`1c21c64fe37b4dbd47372ea443e768b90a1ca009`, `shared/figures/`, copied on
2026-09-18. The source HTML lived under `tools/figures/`; the source
`shared/figures/MANIFEST.md` records its rendering procedure. PNG previews
used Poppler `pdftoppm -singlefile -scale-to 2000 -png`. Historical PDF hashes
below describe the upstream source PDFs; these PDFs are not tracked here.
Figures are reused at the operator’s request; no separate figure license is
inferred. The repository software license does not replace paper rights.

## SHA-256 checksums for the earlier illustrations

PDF hashes below also match the source files byte for byte.

```text
07249b59e603aacf843435be187dd5595b5fa3fcf82809d00511ee5b17c93c51  fig_composition.pdf
0800f8f17b45f2b0a8004d62f903934ad510c3e3702e876b7789f78b55d802de  fig_evaluation.pdf
19f9e182092b3c8fdbe49407fcac46df30e9ec3c87a37d7274616770fb95f00e  fig_human.pdf
0b97611a2c5c79db1175fcf8c15ac914fc1fd467394f28847d90bfd78d941b02  fig_loop.pdf
d6691674de1c6c3a6aefd3d95d4aa035ce0b51043e834bd53da966ada1cef511  fig_composition.png
6b2b20d3b20f3acb6d914b7173fcd81539cdb42da6b30b4650c10368110dd600  fig_evaluation.png
cfaec79b15a9bfe60e74a21fb9b9c87fe47cf751f40c26e5c910273c5296547e  fig_human.png
f70b7c06d10007c0bfb4ed07c95501719ab14bb664dcf939016392c94a61168f  fig_loop.png

```

## Figure 3: TIDMAD exploration and LLM cost

Exported 2026-10-12 from the same published PDF identified above, page 8
(zero-based index 7). Crop box in bottom-left PDF points: `(108, 530, 504, 711)`.
The crop retains both panels, axis labels and the full legend, excluding the
paper caption and surrounding prose. No curves, labels or results are redrawn.

Use the same export procedure with `(3, 7, (108, 530, 504, 711))`.
The SVG retains `viewBox="0 0 396 181"`, with display width `1200`, height `548`
and a white background rectangle `(0, 0, 396, 181)`. The PNG is 3200 pixels wide.

Figure 3 reports estimated API-equivalent LLM costs, not GPU training costs or
invoices. The README's performance statement also refers to Table 1: Run 5
(orchestration without Data Analysis) has 30 valid proposals and best valid
score 2.744; the fixed-workflow conditions have the lowest estimated LLM costs.
This is evidence for the reported TIDMAD conditions, not a task-independent
ranking of execution approaches.

```text
4db756f3d36f82aee79d21b7dad192b5ee807fe513a685129674514b28095c41  figure3.svg
72e028875fad2a3c1590113288e3c6bceee6cc531b2549fc728261910f08673f  figure3.png
```
