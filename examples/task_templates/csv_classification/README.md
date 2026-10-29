# Task template: classification from CSV files

Copy this folder to package your own tabular dataset as a SIDERIUS task. It is
a complete, working task package: it reads your CSV files, scores predictions
with balanced accuracy, checks them with two Health checks and locks one
training setting. You change only the lines marked `EDIT HERE`.

A *task package* is the folder that tells SIDERIUS what your scientific problem
is: where the data is, what the model receives and returns, how a result is
scored and when a result is invalid. The folder holds no data.

## Before you start

- A SIDERIUS checkout installed with `uv sync --group dev --frozen`, and a
  console workspace (`siderius_workspace/`). Stage 1 of the
  [first-hour path](../../../docs/getting-started/README.md#your-first-hour-from-the-example-to-your-own-task)
  creates both.
- Your data as two CSV files with a header row, one row per sample:
  - `train.csv`: the rows models are trained on;
  - `validation.csv`: the rows the research loop scores every model on.

  Each file has the same columns: one label column (the class, as text or a
  number), numeric feature columns, and optionally an ID column with a unique
  value per row. For example:

  ```text
  sample_id,f0,f1,f2,f3,label
  t000,5.1,3.5,1.4,0.2,setosa
  t001,6.3,2.9,5.6,1.8,virginica
  ```

- Decide how to split before you copy anything. The split is a scientific
  choice: rows from the same patient, site or day usually belong in the same
  file, or the validation score is too optimistic. Your coding agent can split
  one CSV for you once you agree on the rule. The package trains only on
  `train.csv` and scores only on `validation.csv`, so the split is exactly
  your two files. Before you use results scientifically, keep the evidence
  that the two files share no sample or group, as
  [required task-owned split evidence](../../../docs/guides/define-a-task.md#required-task-owned-split-evidence)
  describes.
- Keep a separate final test file outside the data folder. The research loop
  never needs it, and nothing in this package reads it.
- A real run trains models, so it needs an NVIDIA GPU with CUDA. Every step on
  this page works without one.

## What is in the folder

| Path | What it is | Edit? |
| --- | --- | --- |
| `task.yaml` | The manifest: names every other file below, plus your CSV file names, label column, class labels, feature count and locked parameters. Paths are relative to this folder. | yes |
| `declared/task_config.yaml` | The task description the agents read, and the model input and output sizes. | yes |
| `declared/task_health.yaml` | The two Health checks, their thresholds and the number of classes. | yes |
| `declared/dataset_profile.json` | The two data partitions (0 = training file, 1 = validation file) and a one-line data source note. | the note only |
| `declared/metric_balanced_accuracy.json` | The main score's name and direction (higher is better). | no |
| `plugins/_csv_task.py` | Reads the CSV files and writes each model's predictions. Holds one optional `EDIT HERE` constant, `TASK_DATA_PATH_ID`. | one constant |
| `plugins/_csv_metrics.py` | Computes balanced accuracy. | no |
| `plugins/_csv_health_views.py` | Hands the predicted classes to the Health checks. | no |
| `plugins/csv_reference_mlp.py` | A small reference model the run must be able to build. | two numbers |

## Package your dataset

The commands use `/absolute/project/siderius_workspace` for your console
workspace and `iris` for your task ID. The folder name under `tasks/` becomes
the task ID, so choose a short name without spaces. Run the commands from the
SIDERIUS checkout's root folder.

1. **Copy the template and your data into the workspace.**

   ```bash
   cp -r examples/task_templates/csv_classification \
     /absolute/project/siderius_workspace/tasks/iris
   mkdir -p /absolute/project/siderius_workspace/data/iris
   cp /path/to/train.csv /path/to/validation.csv \
     /absolute/project/siderius_workspace/data/iris/
   chmod 600 /absolute/project/siderius_workspace/data/iris/*.csv
   ```

2. **Edit the `EDIT HERE` lines**, in this order. Three numbers appear in more
   than one file and must agree everywhere: the class list, the number of
   classes and the number of features.

   | File | What to set |
   | --- | --- |
   | `task.yaml` | `train_file` and `validation_file`: your file names. `label_column`: the label's column name. `classes`: every label value exactly as written in the CSV; the first is class 0. `id_column`: your ID column, or `null` to number the rows. `feature_count`: how many feature columns. Every column except the label and ID is a feature, unless you list the ones to use under `feature_columns:`. |
   | `task.yaml` | `parameter_rules`: keep `train_config.batch_size: exact: 32`, change the number, or delete the rule to let the agents choose. |
   | `declared/task_config.yaml` | `task_description`: your data, target and score in plain words. The two `fixed:` sizes: the feature count (input) and the number of classes (output). Update the descriptions and `output_head_note` to match. |
   | `declared/task_health.yaml` | `symbol_cardinality`: the number of classes. `max_dominant_fraction`: a value above your largest class's share of `validation.csv` (for example 0.8 when the largest class is 60% of rows). |
   | `declared/dataset_profile.json` | `source`: one sentence on where the data comes from and how you split it. |
   | `plugins/csv_reference_mlp.py` | `FEATURE_COUNT` and `CLASS_COUNT`. |
   | `plugins/_csv_task.py` | `TASK_DATA_PATH_ID` (optional): a short identifier for this task's data path, recorded in run identity. Give each task its own value, so two tasks loaded in one process do not share it. Leave the default if you load only this task. |

   Features are passed to models as the numbers in the file. If their scales
   differ by orders of magnitude, standardize them with training-file
   statistics when you prepare the CSV files.

3. **Register the task with the console.**

   ```bash
   .venv/bin/python -m tools.candidate_console add-task \
     --config /absolute/project/siderius_workspace/settings/console.json \
     --manifest /absolute/project/siderius_workspace/tasks/iris/task.yaml \
     --label "Iris species"
   ```

   You do not need `--device`. `add-task` finds this machine's NVIDIA GPUs
   (`/dev/nvidia<N>`), passes them to runs and prints them as
   `candidate_devices: ...`. Add `--no-gpu` for a CPU-only task, or
   `--device PATH [PATH ...]` to pass exactly the device paths you name. To change
   the devices later, edit the `candidate_devices` list in this task's entry in
   `siderius_workspace/settings/console.json`, then restart the console.
   Success: it prints the entry it added and ends with
   `Restart the console to load the new task.` `add-task` checks the console
   entry and folders; it does not read your CSV files. The next step does.

4. **Restart the console and read the Task tab.** Stop `serve` (Ctrl+C) and
   start it again, connect, open **Task** and select your task. A correctly
   packaged task shows:

   - **Main score**: `balanced_accuracy`, higher is better;
   - **Health checks**: `predicts_more_than_one_class` marked **Blocking** and
     `dominant_class_fraction` marked **Recording**;
   - **Locked parameters**: `train_config.batch_size` fixed to 32;
   - the data folder with your two CSV files.

   Select **Count samples**. It reads both files through the package and shows
   the number of training and validation rows. A mistake in the CSV or in
   your edits appears here as a message naming the file and line, the column
   or the label value to fix. Fix it, then select **Refresh**.

Then create an experiment setup for the task on **Workflow** and run it, as in
stage 2 of the
[first-hour path](../../../docs/getting-started/README.md#stage-2-bring-your-own-task).

## What the two Health checks do

A Health check decides whether a model's predictions are usable at all,
separately from how well they score.

- **Blocking** `predicts_more_than_one_class`: a model that predicts the same
  class for every validation row fails, and its result is not a valid
  candidate whatever its score.
- **Recording** `dominant_class_fraction`: the share of rows given the most
  common predicted class is measured and stored with each result. Exceeding
  `max_dominant_fraction` is recorded as a warning; it never invalidates a
  result.

Both are generic checks provided by SIDERIUS. To add or change checks, see
[bring your own Health checks](../../../docs/guides/bring-your-own-health-checks.md).

## How the labels reach the score

The score needs the true label of every validation row, so the package reads
labels from `validation.csv` at the moment a model is scored, not before. A
run first decides which rows each step uses; that decision is made without
access to the data folder, so it records only the file, the fraction of rows
or a row limit, and the seed the run supplies. Training, prediction writing and
scoring each receive the data folder, re-read the file and apply the same
selection, so they all see the same rows. When a step uses only part of a
file, it takes a random subset chosen by that seed, never the first rows, so
the order of rows in your CSV does not matter.

A validation row with no prediction counts as wrong. Predictions for IDs that
are not in the selected validation rows are ignored.

Do not copy the Quickstart example's pattern of storing labels in that
selection: it works there only because the Quickstart regenerates its data
from a fixed seed. The
[data-path contract](../../../docs/agent-reference/mechanisms/data-path-and-scope.md#scopes-for-file-backed-data)
states the rule for coding agents.

## Going further

- Another main score: change `IMPLEMENTS` and the arithmetic in
  `plugins/_csv_metrics.py` and the `id` (and, if lower is better,
  `direction`) in the metric declaration; see
  [bring your own metric](../../../docs/guides/bring-your-own-metric.md).
- More locked or limited parameters: add rules under `parameter_rules`; the
  [composition reference](../../../docs/reference/task-composition.md#section-shapes)
  lists the forms.
- Regression instead of classification: start from the
  [synthetic masked-regression example](../../synthetic_masked_regression/README.md).
- Every manifest section: the [task definition guide](../../../docs/guides/define-a-task.md).

The template's own checks are in
[`test_csv_classification_template.py`](../../../tests/unit/examples/test_csv_classification_template.py)
and, for the console route above,
[`test_csv_task_template.py`](../../../tests/unit/tools/candidate_console/test_csv_task_template.py).
