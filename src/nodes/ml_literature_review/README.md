# src/nodes/ml_literature_review

Public entry `ml_literature_review.py` and canonical `ml_literature_review.md`
define the node. `LiteratureReviewInput`/`LiteratureReviewOutput` live in
`src/agent/schemas/literature_review.py`; the fan-in protocol is
`src/agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py`.
Focused tests: `tests/unit/agent/ml_literature_review/`.
