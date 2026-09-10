# P0 implementation handoff

Status: `p0-docs-v2` DESIGN FROZEN / IMPLEMENTING.
Updated 2026-09-10. C1/C2 committed; C3 minimal entry checks and local review
complete. Next: commit C3 evidence, run terminal bounded checks, publish branch
and open/inspect PR. Merge remains unauthorized.

## Identity, authority and authorization

- Project: one P0 inventory/navigation/minimal-entry documentation PR; no PR
  number yet. Primary design/live ledger: [step-01-user-map.md](step-01-user-map.md).
- Parents: [overall.md](overall.md), [CLAUDE](../../../CLAUDE.md), Paper
  `/home/yuema137/SIDERIUS-Paper/iclr/infra-exp-plan.md` Phase 0 and §21 P0.
- Infra: `/home/yuema137/SIDERIUS`, `docs/organizing-cleanup-plan`;
  base/master `2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0`.
  Last completed commit `49e23151`; C3 evidence is the current docs-only delta.
- Exp: `/home/yuema137/siderius-exp-current`, clean recovery branch
  `recovery/persist-demo-run-records`, `ae12ae13abb6e2c1618f0f185ba468d669868399`.
  Pin `66d3edf2b2045eaf037fb5cc9ecb3dffee94523b`, tree-equal to infra base.
- The operator explicitly adopted v2 during this session and reaffirmed
  semantic commit, scoped branch push, PR creation/update and in-scope repairs.
  The earlier local-only endpoint is superseded. Do not ask per commit/PR.
  No merge, auto-merge, direct push to master, G0 or source relocation.

## Startup and completed milestones

This is the fresh implementation session required by the original kickoff.
Read CLAUDE, handoff, full primary design and binding parents; fully read all
six pinned upstream v0.1.2 resources through the manual route. Web cache misses
and sandbox DNS failure were resolved by approved read-only curl. No installed
matching skill, enabled standards or hooks. Initial branch/base and all four
planning fingerprints matched. All pre-existing planning edits were preserved.
The original planning/initialization handoff remains in C1 Git history;
planning findings and baseline evidence remain in the primary design.

- C1 `efbef63e`: current repository map and five navigation pages (including
  new map), preserved planning conventions and synchronized effort documents.
  24 checks passed in 2.57s; 235 relative links/anchors, 20 base roots, six public
  classes checked. Six node CLI citations unchanged. No physical source moves.
- C2 `49e23151`: advice ownership/format, generated-library behavior and targeted
  CLAUDE history/instruction correction. 40 checks passed in 2.65s. Historical
  status body byte-identical; model/loss lookup differences documented.
- C3: own-venv/source/pin checks PASS; six external compositions PASS, exit 0
  within outer 60s bound (aggregate timing not measured); TIDMAD dry-run PASS,
  0.37s, exactly two own-checkout child commands and workspace absent.
  Exp unchanged; no blocking repair or pin bump needed. Detailed commands,
  versions, lookup correction, N/A items and limitations are in the primary ledger.

## Frozen boundaries and validation

C1 -> C2 -> C3 only. Preserve runtime, configs, tests, public paths, scientific
settings, raw data, outputs and historical evidence. CPU-only diagnostics,
<=60s per subprocess and <=10 minutes total check execution; no environment
rebuild, GPU, LLM, training or campaign. Frozen offline sync made no changes
(95 infra / 94 exp packages). No launched diagnostic remains running.
The process view cannot audit host campaigns; none were launched or stopped.

Gate 1 and Gate 2: NOT REQUIRED for docs-only. Training, inference, scoring,
Health execution, iteration-2 feedback and wheel-only qualification: NOT RUN.
Retained receipts do not qualify this pair today. #423/#424 remain deferred.

CI selector returns FULL SUITE because the new planning path has no mapping;
do not modify the selector or run a local full suite to conceal this.
If remote CI is billing-blocked, use the explicitly approved bounded local
fallback and state its limitations; never call it remote-green or full parity.
Default pyright is unsupported on system Node v10.19.0 and Python is unchanged;
report NOT RUN. Ruff is available. No CI result exists for this PR yet.

## Exact next actions and stop

1. Commit C3 evidence and synchronized mirror after scope/fingerprint checks.
2. Run terminal affected docs/rule/library tests and bounded static/document
   checks on that candidate. Preserve actual results without repeating external
   compositions/dry-run unless their executable inputs change.
3. Push only this working branch and open a master-targeting PR; inspect changed
   paths/body/head and actual CI state. Record any billing block and local fallback.
4. Synchronize terminal evidence, review the final exact diff and finish with a
   clean tree and PR READY FOR OPERATOR REVIEW. No merge or next phase.

## Recovery content fingerprints

Current payload SHA-256, excluding this handoff to avoid self-reference.
These identify tested/reviewed content; they do not confer approval. C1 source
base is `2091acdf`; later checkpoint commits are recorded in implementation evidence.

| File | SHA-256 |
| --- | --- |
| `CLAUDE.md` | `232510f4bf1a484f0ac8c246446800b3b6b5d1f0fab487de0a42dcbf1e1d5fd4` |
| `README.md` | `1986ae7ddd9e538a138f45d21a9de57ce2d542474839a97160d29f459b86b787` |
| `docs/README.md` | `3e880bd3a3f682db201e04ab714435afe57023e143b55f527267aa8f34f371b9` |
| `docs/agent-reference/README.md` | `5b2ea2b81b2abe2881a26b02bc003e57e0046383a45a9715ae9eda84ada43bd6` |
| `examples/README.md` | `d434eb122298c44a89df23d87184d5b37a33f177b302dfd52e9f63584bb5865b` |
| `docs/repository-map.md` | `3b5f9fd2942a3de6b8428f4cf59f486d4257914eb93cc415a390dedcb53e41cb` |
| `advice/README.md` | `79cec162f6a26ada0612496ce4bc23b3415a91829342cd94f9b13717c8485b1d` |
| `ml_models/README.md` | `8b3831d645e2edbdc018bc7fbb8cf3ac2c429d1b6af94bde33eadf3c803204f1` |
| `.structured-coding/plans/infra-exp-p0/overall.md` | `cc9903eea910c3cb4420ecc74757d13a5174b975c49a3ceade04e3815542a2f0` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map.md` | `7543b183a51831447baae59427f7e4da0d508adc3b3f0d23e9579a608db4705d` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map_zh.md` | `00f25b7c3176bbc58b52d903227078d0cd964de629fc8e14720448a23113d721` |
