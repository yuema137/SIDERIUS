"""Tiny synthetic CSV dataset for the CSV classification task template.

Test-only: the template ships no data and downloads nothing. The rows have
the template's default columns (``sample_id``, four features, ``label`` with
three named classes) and are generated from a fixed seed, so counts and
class balance are known exactly.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "examples" / "task_templates" / "csv_classification"
CLASSES = ("setosa", "versicolor", "virginica")
TRAIN_ROWS = 60
VALIDATION_ROWS = 30


def write_csv_dataset(data_dir: Path) -> Path:
    """Write ``train.csv`` (60 rows) and ``validation.csv`` (30 rows, 10 per class)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261029)
    for name, rows, prefix in (
        ("train.csv", TRAIN_ROWS, "t"),
        ("validation.csv", VALIDATION_ROWS, "v"),
    ):
        with open(data_dir / name, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sample_id", "f0", "f1", "f2", "f3", "label"])
            for row in range(rows):
                label = row % len(CLASSES)
                features = rng.normal(loc=float(label), scale=0.3, size=4)
                writer.writerow(
                    [f"{prefix}{row:03d}", *(f"{v:.5f}" for v in features), CLASSES[label]]
                )
    return data_dir


def copy_template(destination: Path) -> Path:
    """Copy the template folder as a user would; return the copied ``task.yaml``."""
    shutil.copytree(TEMPLATE, destination)
    return destination / "task.yaml"
