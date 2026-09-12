# Cache consolidation tests

The owner is [`agent.cache_consolidator`](../../../../src/agent/cache_consolidator.py), with [`CacheEntry`](../../../../src/agent/schemas/cache_entry.py) as its persisted schema. `test_cache_consolidator.py` uses a fake bridge and synthetic findings to cover no-op paths, same-meaning merge, supersession/contradiction, evidence union, rank caps and archive overflow; assertions also bound bridge calls and reject malformed responses. This catches policy drift that schema validation cannot express. `goldens/` is fixture data owned by this family. Focused route:

`.venv/bin/python -m pytest tests/unit/agent/cache/test_cache_consolidator.py -q`
