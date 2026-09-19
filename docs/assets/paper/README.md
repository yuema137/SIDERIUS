# Paper illustrations

Four SIDERIUS-Paper illustrations support the root README: framework
composition, the reference loop, evaluation roles, and human participation.
The original PDFs are copied unchanged; PNG previews render them for Markdown.
Click any preview in the root README to open the vector PDF.

These are conceptual illustrations. The loop and composition figures show the
core capabilities and literature review; they do not depict the optional Data
Analysis extension. Current interfaces and configuration are documented in the
framework guides linked beside each figure.

## Source and reproduction

- Source repository: `git@github.com:yuema137/SIDERIUS-Paper.git`
- Source checkout revision: `1c21c64fe37b4dbd47372ea443e768b90a1ca009`
- Source directory: `shared/figures/` (read-only during this update)
- Copy date: 2026-09-18
- Source manifest: `shared/figures/MANIFEST.md`
- Original figure sources: `tools/figures/fig_{composition,evaluation,loop,human}.html`
- PDF renderer recorded by the source manifest: `tools/figures/render.sh`
- PNG conversion: Poppler `pdftoppm` 0.86.1

```bash
for name in fig_composition fig_evaluation fig_loop fig_human; do
  pdftoppm -singlefile -scale-to 2000 -png \
    "docs/assets/paper/$name.pdf" "docs/assets/paper/$name"
done
```

The source manifest dates composition, evaluation, and loop figures to
2026-08-25, and the human figure to 2026-08-21. The human figure retains its
original visual style. Figures are reused at the operator's request; the source
does not state a separate figure license, and no license is inferred.

## SHA-256 checksums

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
