# README result figure provenance

## Scope and source snapshot

`physics.svg` and `cancer.svg` render `data.json`, a frozen 2026-10-14 result
snapshot. The README displays physics first. These are reported reference
comparisons, not a new matched rerun or an assertion of current state of the art.
No training, scoring, selection or experiment configuration changes accompany
this presentation. The snapshot contains numeric results only, not raw data,
credentials, private deployment paths or model weights.

## Physics

Source: [SIDERIUS paper](https://zenodo.org/records/23071121), Figure 4 and
Appendix E.2. The three SIDERIUS values are published validation R² results;
S4D values are the reported human-designed reference results. The reference
runs were not rerun with these campaigns. This panel does not represent TIDMAD.
`Δ R²` is SIDERIUS minus the reference, not a relative percentage improvement.

## Cancer

The eight values are the best successful Formal test AUPRC from the completed
SIDERIUS campaigns in the frozen snapshot; `selected_iteration` records the
winning iteration. The campaigns used adaptive test-score feedback to guide
search. Thus these values are search-selected results, not an untouched final
holdout evaluation. This distinction appears in the figure subtitle.

The baseline architecture is TREE:
[Su et al., Nature Biomedical Engineering 9, 371–389 (2025)](https://doi.org/10.1038/s41551-024-01312-5).
The numeric TREE values retain the transcription used in the earlier comparison,
from the [published eight-network comparison](https://www.aibuildai.io/blog-cancer-gene-identification).
They have not been independently recomputed from TREE predictions here.
No AIBuildAI model scores are plotted. The SIDERIUS campaign snapshot is not a
result reported by the TREE or SIDERIUS physics papers.

`Δ AUPRC (percentage points)` is 100 × (SIDERIUS − TREE); it is not the relative
change divided by TREE. The Cancer axis starts at 0.50, visibly labelled on the
axis; the physics axis starts at zero. Do not infer improvement ratios from
bar lengths or compare the magnitudes of R² and AUPRC differences.

## Rendering

`render.py` reads only the adjacent snapshot. It never loads live workspaces or
refreshes scientific values. Colors, neutral surfaces and typography follow the
README architecture figures: primary blue for SIDERIUS, gray for the reference,
and blue-gray text. SVG fonts are outlined so GitHub does not require fonts or
external assets. PNG files are inspection previews, not required README assets.

From a checkout with its own frozen development environment:

```bash
MPLCONFIGDIR=/tmp/siderius-result-figure-cache .venv/bin/python \
  docs/assets/results/render.py --output-dir /tmp/siderius-result-previews
```

Inspect both previews before replacing the checked-in SVGs. Values retain their
full precision in JSON; scores display three decimals, R² differences three,
and AUPRC differences one percentage-point decimal. This formatting affects
only the figure, not agent feedback or stored experiment results.
