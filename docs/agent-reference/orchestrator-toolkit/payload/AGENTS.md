# SIDERIUS tools for this research workspace

Locate the toolkit root before opening relative paths, including after changing
working directory. It is the ancestor containing both `SIDERIUS-RUN.md` and
`.agents/skills/siderius-toolkit/SKILL.md`. Use its absolute path for subsequent
reads. For a session started in that root or any child directory:

```bash
toolkit_root="$PWD"
while [ ! -f "$toolkit_root/SIDERIUS-RUN.md" ] || [ ! -f "$toolkit_root/.agents/skills/siderius-toolkit/SKILL.md" ]; do
  [ "$toolkit_root" != / ] || { echo "Toolkit root not found" >&2; exit 1; }
  toolkit_root="$(dirname "$toolkit_root")"
done
cat "$toolkit_root/SIDERIUS-RUN.md" "$toolkit_root/.agents/skills/siderius-toolkit/SKILL.md"
```

This shell variable belongs to that shell invocation; use the resolved absolute
path in later commands. If the run declaration supplies an explicit toolkit
root, use that path instead. Do not recursively search unrelated workspaces.

The run declaration identifies the task instructions to read, exact installation, enabled capabilities,
authorized paths, model routing and applicable resource limits. Follow those
task instructions and their referenced task package. This toolkit supplies
interface guidance; the task and run declaration own scientific, resource,
deadline, information-access and submission requirements. If they disagree,
report the conflict before the affected operation.

Use [$siderius-toolkit](.agents/skills/siderius-toolkit/SKILL.md) to discover the
provided capabilities. Read that index at startup; before first using a
capability, read its linked guide and the relevant native-schema reference.
File links are relative to the document containing them, not the shell's cwd.
A missing guide or unreadable authorized input is a concrete setup issue.

Choose order, repetitions, branching, parallelism and stopping from the evidence
and the unchanged experiment objective and resource limits. The toolkit index
does not prescribe a workflow. Use the existing SIDERIUS agents for operations
they support. Before replacing an agent operation with handwritten code, read
[capability selection](.agents/skills/siderius-toolkit/references/selection.md)
and establish the concrete unsupported requirement. Thin code that validates
inputs, calls native APIs, transfers artifacts or formats results is normal
orchestration; it does not replace an agent.

All capability calls, your own reasoning, custom code, failures and retries
consume the same run-wide resources and continuing clock. A new process or
capability call does not open another budget. The run declaration identifies
permitted external-information channels; provider access does not itself grant
permission to retrieve scientific information from another source.

When writing a continuation or handoff summary, retain the absolute paths to
this index, `SIDERIUS-RUN.md`, the skill index and the current capability guide,
plus the current request/output paths and any unmet prerequisite. State that
SIDERIUS remains available for supported operations. Keep this pointer compact;
reopen the relevant reference when needed instead of copying the whole manual.

On context recovery, reopen this index and `SIDERIUS-RUN.md`, then the relevant
capability guide. If you delegate, pass these exact paths, the applicable
restrictions and explicit artifact references to the delegated work. Do not
assume another session inherits the files you have read.
