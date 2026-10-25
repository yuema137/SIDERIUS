# Native writer ownership

`core.native_writer` owns cooperating same-user writer exclusion. It does not own
iteration selection, scientific history, retry, process cleanup, or resume. Native
shell and direct iteration entry points acquire it before workspace mutation and
failure-handler writes. Config printing, capture export and dry-run bypass writes.

## Identity and storage

The canonical workspace path selects a private sibling directory
`<parent>/.<workspace-name>.siderius-writer`. The parent must already exist and be
writable. Directory permissions are 0700; control files are 0600, owned by the
current user, regular and opened without following symlinks. Typed records are
bounded to 4096 bytes. The stable `writer.lock` inode is never removed or replaced.
Aliases resolving to the same workspace share the lock; different workspaces do
not. This is not protection against a malicious actor with the same user identity.

Managed native operations create the owner inside the existing sandbox. Their
scientific workspace is `envelope/workspace`; the sibling control directory lies
inside the already writable envelope. No mount or cross-sandbox FD transfer is added.

## Supported ownership

On Linux every cooperating native root acquires a nonblocking exclusive flock.
Uncaptured foreground chains and direct iterations use ephemeral ownership only.
Their existing scientific failure/continuation policy remains unchanged. Other
platforms retain legacy direct behavior without this guarded ownership guarantee.

A fresh captured foreground chain additionally records immutable registration
(`captured-native-foreground/v1`, canonical workspace, capture digest) and a durable
claim UUID before starting the original shell. This registration also applies to
the same foreground chain launched inside a detached operation. Registration is
never inferred from task names, existing scientific files or current defaults.
Direct roots cannot enter registered workspaces; effectful resume is not supplied
by this package. Capture admission still requires an absent workspace.

The root passes its actual lock FD to the synchronous shell and iteration child.
Private `SIDERIUS_NATIVE_WRITER` transport is validated against canonical workspace,
stable file device/inode, Linux `/proc/self/fdinfo` exclusive whole-file FLOCK, and
registered claim identity where applicable. An independently opened unlocked FD
for the same inode is insufficient. Validation never acquires a purported inherited
lock. Registered iterations create an exclusive `iteration.active` marker.

Slurm submission holds ephemeral ownership through history/stale checks and initial
workspace/log creation, then unlocks and clears transport before the first `sbatch`.
Each compute iteration acquires its own ephemeral ownership. Existing `afterany`
dependencies remain unchanged; jobs can start during submission. Registered Slurm
entry is unsupported. Slurm has no durable full-chain ownership or recovery claim.

## Cleanup and uncertainty

The existing subprocess supervisor constructs `ProcessLifecycle`. A context-local
observer inside native iteration scope sees the lifecycle after finalization and
before return/raise. It marks uncertainty for an unreaped child, cleanup errors,
an owned group not proven absent, or an abnormal plain child without group cleanup
proof. The synchronous native skill/sandbox/phase path carries this context.
No context transfer to arbitrary future threads or processes is promised.

Sticky in-memory uncertainty is set before persisting `unresolved`. Callback errors
cannot replace the original supervision exception. If persistence fails, active
participation remains, preventing the shell owner from clearing its claim. Normal
participant completion removes active participation. Persisted uncertainty can
coexist with the same shell's original continuation policy; it always blocks a new
independent owner. A scientific nonzero outcome alone does not establish leaked
processes, and a zero exit alone does not establish cleanup.

The launcher forwards TERM/INT/HUP to the original shell and waits for it in the
same session. The original shell and subprocess supervisors retain their signal,
drain and cleanup policies. A killed owner or participant leaves its durable claim
or active marker. Even once all flock holders die, a new owner refuses. There is
no PID-based reclaim, expiry, force-unlock, daemon discovery or second scheduler.
Deliberately escaped daemon descendants are outside the existing supervisor's
guarantee. Legacy unregistered ownership provides no durable crash guarantee.

## Inspection and recovery limits

`inspect_writer` and `python -m core.native_writer inspect --workspace PATH` report
`active`, `registered_idle`, `unresolved`, `unregistered`, or `invalid` without
creating control or scientific files. Inspection is a momentary observation, not
launch authorization or proof of scientific completion. An invalid state also
refuses launch. Public ownership refusals use exit 78 at shell/direct CLI entry.
In particular, `registered_idle` is not proof of universal descendant absence:
successful non-owned children retain cooperative direct-child semantics. A future
resume admission must additionally establish that the outer operation is inactive
and its supervision cleanup proves absence. Claim state alone cannot grant reuse;
an active outer operation must refuse even if its native claim is idle.

Unresolved registration remains blocked except through explicitly verified detached
continuation admission. Do not delete or rewrite control metadata, infer safety from a
missing PID, reconstruct a capture, or label a new workspace as resumed work.
GUI, Professional and Assistant callers consume this same backend contract.

## Explicit successor ownership primitives

`resume.locked_registered_writer` opens existing state and the permanent lock,
without creating directories or releasing durable records on exit. Its typed
snapshot binds registration, claim, participation and unresolved records to the
same bounded bytes that were parsed, plus lock device/inode. Orphan or mismatched
claim references refuse. This lock is not outer-process cleanup evidence.

An admitted operation can publish a write-once `successor.<predecessor-UUID>.json`
reservation under this lock. `adopt_reserved_writer` requires the exact reservation
and snapshot, then writes `adopted.<successor-UUID>.json` before removing the prior
participant, unresolved and claim records in that order. It publishes the new
claim and transfers the same held descriptor to `WriterLease`. Adoption is never
replayed, even for the same UUID; interrupted transitions retain their permanent
adoption marker. Registration and the lock inode are never replaced.

The operation owner must separately prove outer inactivity, cleanup absence and
unchanged scientific history. Core does not parse operation terminals or select an
iteration. Native entry rechecks the original capture, bounded baseline and private
reservation before adoption. `run_shell_with_lease` consumes the adopted lease with
the same signal/wait/release behavior as fresh `launch_shell`; no new supervisor
or cleanup mechanism is introduced. These internal primitives do not authorize
manual metadata editing or bypass fresh capture admission.
