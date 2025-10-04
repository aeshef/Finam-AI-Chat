#!/usr/bin/env python3
"""
Generate submission.csv using only offline mapping (no LLM calls).

Usage:
  python scripts/generate_submission_offline.py --test-file data/processed/test.csv --output-file data/processed/submission.csv
"""
from __future__ import annotations

import csv
from pathlib import Path
import sys

# Ensure project root on sys.path for `src` imports when run directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import click

from src.app.leaderboard.offline_map import offline_map


@click.command()
@click.option(
    "--test-file",
    type=click.Path(exists=True, path_type=Path),
    default="data/processed/test.csv",
    show_default=True,
)
@click.option(
    "--include-train",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Optional public train.csv to include (union with test) for full leaderboard eval",
)
@click.option(
    "--output-file",
    type=click.Path(path_type=Path),
    default="data/processed/submission.csv",
    show_default=True,
)
def main(test_file: Path, include_train: Path | None, output_file: Path) -> None:
    rows_by_uid: dict[str, dict[str, str]] = {}
    def _load_csv(path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                uid = row.get("uid", "").strip()
                q = row.get("question", "").strip()
                if uid:
                    rows_by_uid[uid] = {"uid": uid, "question": q}

    _load_csv(test_file)
    if include_train:
        _load_csv(include_train)

    results: list[dict[str, str]] = []
    for r in rows_by_uid.values():
        m = offline_map(r["question"])  # no context known here
        if m is None:
            results.append({"uid": r["uid"], "type": "GET", "request": "/v1/assets"})
        else:
            method, path = m
            results.append({"uid": r["uid"], "type": method, "request": path})

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["uid", "type", "request"], delimiter=";")
        writer.writeheader()
        writer.writerows(results)
    click.echo(f"Wrote {len(results)} rows to {output_file}")


if __name__ == "__main__":
    main()



