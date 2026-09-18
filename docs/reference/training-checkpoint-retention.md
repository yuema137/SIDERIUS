# Training-checkpoint retention

The trainer writes one original `.pth` file per successful attempt. Scoring,
round Health and trained-model certification consume it. Certification copies
the exact weight bytes into an immutable, content-addressed `.pt` blob and
records a `TrainedModelArtifactRef` on the scored attempt. Historical model
inference uses that certified blob. This policy never deletes certified blobs
or their artifact documents, whether the attempt is Trial or Formal.

By default, the tuner collects each attempt's exact original `.pth` and retires
it after the whole tuner iteration and its run output have completed. The
next outer iteration starts only after this finalization returns.
`--retain_training_checkpoints` keeps these
originals as well. The resolved switch is part of the run lock; it cannot be
changed on resume. This switch is independent of `--retain_model_outputs`.

A scored attempt without a certified model keeps its original for inspection.
An attempt that never produced a usable scalar score, including a completed
scorer whose output was invalidated by Health, can retire its original after its
failure is recorded in the completed run output. If that record is missing,
the original stays for investigation. The tuner checks the original's digest and size against
the certified artifact and verifies the blob before deleting anything. A
missing or invalid certificate refuses cleanup and stops the run as an infra
failure, rather than treating the candidate as scientifically invalid.

Every disposition is appended to
`training_checkpoint_retention_receipts.jsonl` in the tuner workspace. A
`retirement_planned` receipt is synced before unlinking, followed by a
`retired` receipt after unlinking. If the process or host stops between these
events, the planned receipt identifies an incomplete retirement; operators
must reconcile it against the source file before treating cleanup as complete.
Receipts name the run, attempt and model, and record the original digest and
byte count when the file existed.
