# Literature review node

`MLLiteratureReviewAgent` turns interpretation bottlenecks and model context
into paper search/resolution, extraction and typed evidence for proposal
generation. It may use Semantic Scholar/arXiv and write cache artifacts; it
does not train models or discover a task composition.

The standalone CLI requires `--task_composition`, `--data_dir` (an existing
directory for the full task binder), and `--lit_review_config`. Use an absolute
external literature YAML path; relative knob paths retain checkout-root
anchoring. Contradictory history metric stamps refuse before the agent runs;
matching or absent stamps do not prove whole-task compatibility. See the full
guide for the invocation and unchanged typed API.

- [Entry and CLI](ml_literature_review.py) · [full guide](ml_literature_review.md)
- Schemas: [LiteratureReviewInput/LiteratureReviewOutput](../../agent/schemas/literature_review.py)
- Fan-in to proposer: [ml_literature_review_to_ml_model_propose](../../agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py)
- Focused controlled-bridge/resolver tests: [tests/unit/agent/ml_literature_review](../../../tests/unit/agent/ml_literature_review/)

Live retrieval and PDF extraction are effectful and require an explicitly
configured run; resolver/extraction helpers are private.
