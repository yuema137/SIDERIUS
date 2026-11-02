# Example composition fingerprint receipts

The Quickstart observable-additivity test and the single-file masked-composition
test pin independently recorded fingerprints. `tests/helpers/preflight_fingerprint.py`
captures their canonical payloads with only `preflight_estimator` and
`inference_preflight` removed. Do not replace their expected hashes with values
computed from the same composition during the test.

## Sampling-seed source update (#1342)

The example task plugins now reject missing sampling seeds. Their source hashes
are legitimate fingerprint inputs even when evaluation and observables are absent.
The two receipts below include that source update. The masked example's separate
effective Health receipt remains unchanged.

| Example | Pre-#1342 receipt | Current source receipt |
| --- | --- | --- |
| Quickstart | `5afaff5876223154c1214d2d4b2b7ce90c603f729ac963c8c3907d8f48c6b21d` | `326197d79814cd71cd3c2be8ca04caa22cb211fffdcfb26004f864c471eb4a4b` |
| Synthetic masked regression | `ab844635ae8c242e112d0bb346c644b79d15165a666510d211d28378cf55d16d` | `e429f8d71015cc97649f7c61b0f76ebf1d1af75f30b78a3d4813a87e6ba8f233` |

The #1293 receipt audit compared captured payloads against the composer from
master `f4a0bfc35e98997a0ae8a1ce46117e21836b0a0e`: both were identical, with
no evaluation key. Replacing only each plugin's source hash with its value from
the first parent of #1342's merge (`be4aaefe^1`) reproduced the old receipt exactly.
Each source hash occurs twice, in the corresponding plugin identity entries.

| Plugin | Previous content SHA-256 | Seed-refusal content SHA-256 |
| --- | --- | --- |
| `examples/quickstart/plugins/_quickstart_task.py` | `f202e1bc5fefc8dcc5e671b63fb4dc80c25f08339cd49bb28afdc7433ba0aa56` | `7ade2b7b290ec96e704481604110fc7bc627f6987b09056c5670c3f0d5dcebd0` |
| `examples/synthetic_masked_regression/plugins/_masked_task.py` | `5c37f1664e48c6bf510a401e7441b0a35d11cbe44dc700476c0e4f76b7609241` | `1e7d106dbf71df6ea7c319d213a10f02ffe1d658a80dc7fe176a15f029a1c93c` |

When a receipt fails, inspect the payload and its source inputs before repinning.
Absent optional declarations must not add semantic fields. Preserve independent
Health/configuration receipts unless their own declared inputs change.
