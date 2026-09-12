# tests/unit/tools

Tool tests protect contributor-gate wording, Markdown link resolution, token
baseline reporting, and documentation census rules. They inspect local files;
no CI service is contacted.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/tools/test_contributor_gate_makefile.py -q`

Owner: `src/tools/` and repository documentation contracts.
