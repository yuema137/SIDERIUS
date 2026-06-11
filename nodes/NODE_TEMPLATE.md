<!--
This file is the canonical template for SIDERIUS node documentation. Every
node's `.md` file under `nodes/<node_name>/<node_name>.md` MUST follow this
structure exactly — same section headings in the same order, same table
shapes, same code-block language tags.

Placeholder convention:
  <angle brackets>         — replace with the concrete value
  <NodeClassName>          — the Python class name, e.g. MLLiteratureReviewAgent
  <node_dir>               — the directory name under nodes/, e.g. ml_literature_review
  <node_module>            — the .py filename without extension, same as <node_dir>

Rules for filling in this template per-node:
  - Every section listed below MUST appear in every node doc, in the same
    order. If a section does not apply, write "None." or "N/A" — do not omit.
  - The Input / Output tables MUST mirror the actual Pydantic schema field
    by field. Do not summarise from memory; read the schema source.
  - If a field's description is missing from the schema, write what the
    field actually does based on reading the code, and add a trailing
    `[inferred from code]` note in the Description cell.
  - CLI arguments table covers only what the node's `argparse` block in
    `main()` exposes. Do not document Python-only fields here — those
    belong in the Input table.
  - Workflow-populated input fields that a standalone caller would never
    set may move into the "Workflow-populated fields" subsection at the
    end of the Input section, to keep the primary table readable.
  - **Node type** values:
      * `standalone-capable` — the node can be invoked directly via its
        CLI `main()`, reading inputs from disk and writing outputs to
        disk, without the full chain workflow.
      * `workflow-only` — the node is only meaningfully invoked from
        within `workflows/model_exploration.py` (or a sibling workflow)
        because it depends on state the workflow assembles (e.g. live
        protocol-passed inputs, per-iteration in-memory handoffs).
-->

# <NodeClassName>

> <One sentence: what this node does in the SIDERIUS pipeline.>

## Position in the pipeline

- **Node type**: <workflow-only / standalone-capable> — <one-line justification: what makes it CLI-runnable, or what workflow state it depends on>
- **Upstream**: <which node(s) feed into this one, or "none" if it is the entry point>
- **Downstream**: <which node(s) consume this node's output>
- **Protocol**: <which protocol function connects this node to the next, e.g. `local_full_context` in `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`>

## Input

**Schema**: `<InputClassName>` in `agent/schemas/<filename>.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `<field_name>` | `<type>` | Yes / No | `<default or —>` | <what it means and how it affects behavior> |

<!-- Optional subsection. Use ONLY if a node has fields the workflow always
populates that a standalone caller would never set; move them out of the
primary table above into this subsection. Otherwise omit. -->

### Workflow-populated fields

<!-- Same table shape as above. Examples: storage paths the workflow
threads in, hardware_context manifests, run-level data-sampling parameters
the workflow propagates from CLI flags, etc. -->

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `<field_name>` | `<type>` | Yes / No | `<default or —>` | <what it means; note the workflow site that populates it> |

## Output

**Schema**: `<OutputClassName>` in `agent/schemas/<filename>.py`

| Field | Type | Description |
|---|---|---|
| `<field_name>` | `<type>` | <what this field contains> |

## CLI usage

```bash
python nodes/<node_dir>/<node_module>.py \
    --<arg> <value> \
    --<arg> <value>
```

### CLI arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--<arg>` | `<type>` | `<default>` | <description> |

## Python API usage

```python
from nodes.<node_dir>.<node_module> import <NodeClassName>
from agent.schemas.<schema_file> import <InputClassName>

inp = <InputClassName>(
    <field>=<value>,
    # ...
)
agent = <NodeClassName>(provider="gemini", model_id="gemini-3.1-pro-preview")
output = agent.run(inp)
```

## Storage outputs

<Describe what files this node writes to disk, at what paths, and in what
format. If the node writes nothing, say "None.">

## Key behavioral notes

- <Any non-obvious behavior, constraint, or gotcha that a caller must know.>
- <Known failure modes and what triggers them.>
- <Any interactions with environment variables or config files.>

## Dependencies

- **LLM**: <which LLMBridge calls this node makes, e.g. "2 calls per run: `generate_text` (reasoning) + `generate` (commit JSON)">
- **GPU**: <required / not required; brief note on what GPU is used for if required>
- **External services**: <S2 API, TIDMAD data dir, HuggingFace, etc., or "none">
