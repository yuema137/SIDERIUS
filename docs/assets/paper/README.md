# Paper illustrations

The root README uses the current paper's task/evaluation overview (`figure1`)
and end-to-end research loop (`figure2`). The older framework composition,
reference loop, evaluation-role, and human-participation illustrations remain
available below for documentation that specifically links them.
The original PDFs are copied unchanged where available; PNG previews render them
for Markdown. The current paper build supplies `figure1.png` and `figure2.png`
as rendered submission figures.
The root README embeds PNGs; it does not link those previews to vector PDFs.

These are conceptual illustrations. The current `figure2.png` includes Data
Analysis and literature inputs. The older `fig_loop` and `fig_composition`
illustrations omit Data Analysis. Use the framework guides for executable
interfaces and configuration.

## Earlier framework illustrations: source and reproduction

- Source repository: `git@github.com:yuema137/SIDERIUS-Paper.git`
- Legacy source checkout revision: `1c21c64fe37b4dbd47372ea443e768b90a1ca009`
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

## Current paper-build figures

| Asset | Meaning | Source |
| --- | --- | --- |
| [`figure1.png`](figure1.png) | Task package declarations, evaluation roles, scoreability, and Health | `SIDERIUS-Paper/iclr/build/submission_audit/figure_1.png` |
| [`figure2.png`](figure2.png) | Data Analysis/literature inputs and the Interpret → Propose → Implement → Validate → Train & Tune loop | `SIDERIUS-Paper/iclr/build/submission_audit/figure_2.png` |

Current paper-build source checkout revision used for these two files:
`8ef64a181e5b8e606ff6bdb88433c4ecdd7ab31f`.
The files were copied read-only from the paper checkout on 2026-09-28.

```text
f39ed5c2ba1ea860434bf540902648540efe16692b6d7ecf23bb0f3d3ac5839a  figure1.png
7cefd3de80672aaed3c422e15ddbc3b5576283a7d1e0b79a37e59b31b4e72a2f  figure2.png
```

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
