# Writing a module README and its technical reference

Audience and review rules are owned by
[CLAUDE.md](../../CLAUDE.md#documentation-audience-and-review). This template
applies those rules to a subsystem directory; it does not create another rule
ledger.

## README: help a person choose their next step

Use a descriptive title and a few sentences explaining what the module does.
Introduce project-specific terms before relying on them. Add only the sections
that help this directory's reader:

```markdown
# <module purpose>

<What this directory does, what a reader can accomplish here, and its boundary.>

## Start here

<One safe route or short example, with prerequisites and expected effects.>

## Find the right part

| Need | Owner or next directory |
| --- | --- |
| <concrete task> | <link> |

## Technical detail

<Link the owning interface, configuration, failure, and validation references.>
```

A README is not a required thirteen-section contract. Avoid duplicating schema
fields, internal control flow, full refusal tables or dated validation ledgers.
A short developer-facing directory map is still human-facing: explain what the
code is for before listing its identifiers.

## Non-README reference: preserve the engineering contract

Prefer an existing node, skill or mechanism reference when it already owns the
subject. Otherwise add one adjacent, clearly named technical document. Include
applicable scope, interfaces, input/output schemas, defaults, state and filesystem
effects, failure behavior, extension boundaries, source owners and focused test
evidence. Do not omit a material caveat just to shorten the README.

Use source paths and symbols rather than fragile line-number inventories.
Link neighboring responsibilities to their owners. Distinguish current source
behavior from historical observations and unfinished designs. When moving detail,
check inbound links and keep useful old README anchors as navigation to the owner.

Node contracts continue to follow
[NODE_TEMPLATE.md](../../src/nodes/NODE_TEMPLATE.md). Cross-package semantics
belong in the [mechanism references](mechanisms/README.md).
