"""A literal validation-probe SeedContext for tests that run model probes (issue #983)."""

from core.training_seeds import SeedContext

#: Tests that are not about seeding still need a probe context: probes refuse
#: to run unseeded (MissingRunSeed).
PROBE_SEED = SeedContext(run_seed=11)
