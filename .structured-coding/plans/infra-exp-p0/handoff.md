# P0 implementation handoff

Status: `p0-docs-v2` implementation and review packet complete; PR #426 published.
Updated 2026-09-10. C1/C2/C3 and local terminal checks complete.
Final candidate SHA, exact CI disposition and terminal clean-tree verification
are recorded in [PR #426](https://github.com/Galileo-Sandbox/SIDERIUS/pull/426)
metadata after this record commit. Continue following actual CI until its
required verdict is established. Merge remains unauthorized.

## Identity, authority and authorization

- Project: P0 inventory/navigation/minimal-entry documentation PR #426. Primary design/live ledger: [step-01-user-map.md](step-01-user-map.md).
- Parents: [overall.md](overall.md), [CLAUDE](../../../CLAUDE.md), Paper
  `/home/yuema137/SIDERIUS-Paper/iclr/infra-exp-plan.md` Phase 0 and §21 P0.
- Infra: `/home/yuema137/SIDERIUS`, `docs/organizing-cleanup-plan`;
  base/master `2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0`.
  C1 `efbef63e`, C2 `49e23151`, C3 `1d07826a`; current delta is terminal
  bookkeeping in the four effort documents only.
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
report NOT RUN. Ruff is available. Automatic CI `34525368657` started on the first published head; no billing
block was observed. The final record commit gets its own automatic CI.
Local terminal checks at `1d07826a`: 40 passed in 2.68s, Ruff check PASS,
format PASS (1,187 files), all exit 0. No user-doc or executable delta follows.

## Exact next actions and stop

1. Commit/push this final bilingual evidence update; verify its diff is limited
   to the four effort documents and the tested inputs are unchanged.
2. Follow the final candidate automatic CI; record run/head/verdict in PR #426
   metadata, not in another acceptance-affecting commit. Repair in-scope failures
   if needed; the earlier run is not the final candidate evidence.
3. Verify clean local/remote branch identity and PR diff/body. Once final CI
   passes (or an observed billing block activates the approved fallback), report
   PR READY FOR OPERATOR REVIEW / context CLOSED, awaiting operator action.
   No merge, auto-merge, master push or next phase.

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
| `.structured-coding/plans/infra-exp-p0/overall.md` | `2de7024e8a76cd85b75d50380f1e06b4db38b57e88c879829b7fea8637bcc3e2` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map.md` | `a8ea76087b3993b5632426f18b890cc5a8fb610b730625fc91bc5878a4f53a03` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map_zh.md` | `04387d82c657d18008233445c29bc4a33c377eab108974b61a6d78c2267aea75` |
