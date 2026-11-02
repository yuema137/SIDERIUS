"""A one-term weighted_sum ``evaluation:`` section over the quickstart primary metric.

Composed into the quickstart manifest it yields a distinct effective selection id
(``evaluation.weighted_sum.v1.<sha>``, higher) while the source metric stays
``accuracy``, so tests can tell which of the two specs a consumer used.
"""

FORMULA_EVALUATION = {
    "components": [
        {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"}
    ],
    "selection": {
        "kind": "formula",
        "formula": {
            "family": "weighted_sum",
            "params": {
                "terms": [
                    {
                        "component": "quality",
                        "weight": 1.0,
                        "lower": 0.0,
                        "upper": 1.0,
                        "out_of_range": "refuse",
                    }
                ]
            },
        },
    },
}
