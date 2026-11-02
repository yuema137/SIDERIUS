# Releases

Each page below describes one SIDERIUS release: what is new, what behaves
differently from the previous release, known limitations and how to upgrade.

To upgrade:

1. Check which version your checkout has: `grep '^version' pyproject.toml`
   prints, for example, `version = "1.1.0"`.
2. Open the page for the release you are moving to and read what changed
   (in v1.1.0, **Changed behavior for v1.0.0 users**) before updating. Runs
   started with an older version usually cannot be resumed after the upgrade.
3. Follow that page's upgrade steps (in v1.1.0, **Upgrade steps**). Success: `uv sync --group dev --frozen`
   exits 0 in the updated checkout and the version line shows the new release.

- [v1.1.0](v1.1.0.md) — experiments written with your coding agent as workflow
  files, research loops you can pause and resume with advice, declared task
  evaluation with weighted-sum selection, no-setup pseudo test runs, an example
  bundle and CSV task template, recorded run seeds, more LLM providers and an
  experimental browser console; real runs need an NVIDIA GPU, and runs from
  earlier versions cannot be resumed.
- [v1.0.0](v1.0.0.md) — setup review, execution protection and explicit task bindings.
- [v0.2.1](v0.2.1.md) — bounded HDF5 reads, loader-inclusive timing and
  explicit cooperative training allocation.

- [v0.2.0-rc.6](v0.2.0-rc.6.md) — prerelease metadata for the coordinated
  post-provenance-fix qualification pair.
- [v0.2.0-rc.4](v0.2.0-rc.4.md) — prerelease metadata for the final
  pre-qualification framework candidate.
- [v0.2.0-rc.3](v0.2.0-rc.3.md) — prerelease metadata for the task-owned
  custom-loss qualification candidate.
- [v0.2.0-rc.2](v0.2.0-rc.2.md) — prerelease metadata for the latest
  framework-only candidate.
- [v0.2.0-rc.1](v0.2.0-rc.1.md) — generic framework prerelease metadata.
