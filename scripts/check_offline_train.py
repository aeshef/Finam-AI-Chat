#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path
import os
import sys

# Ensure project root on sys.path for `src` imports when run directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.leaderboard.offline_map import offline_map
from src.app.registry.endpoints import EndpointRegistry


def main(train_file: str = "data/processed/train.csv") -> None:
    rows = []
    with open(train_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)

    total = len(rows)
    correct = 0
    type_ok = 0
    path_ok = 0
    mismatches = 0
    by_schema = {}
    for r in rows:
        q = r["question"]
        true_type = r["type"]
        true_path = r["request"]
        true_schema = EndpointRegistry().classify_path(true_path) or "other"
        mapped = offline_map(q)
        if not mapped:
            mismatches += 1
            by_schema.setdefault(true_schema, {"total": 0, "exact": 0}).update({"total": by_schema.get(true_schema, {"total":0}).get("total",0)+1})
            continue
        m_type, m_path = mapped
        if m_type == true_type:
            type_ok += 1
        if m_path == true_path:
            path_ok += 1
        if m_type == true_type and m_path == true_path:
            correct += 1
            by_schema.setdefault(true_schema, {"total": 0, "exact": 0})
            by_schema[true_schema]["total"] = by_schema[true_schema].get("total", 0) + 1
            by_schema[true_schema]["exact"] = by_schema[true_schema].get("exact", 0) + 1
        else:
            mismatches += 1
            by_schema.setdefault(true_schema, {"total": 0, "exact": 0})
            by_schema[true_schema]["total"] = by_schema[true_schema].get("total", 0) + 1

    print(f"Total: {total}")
    print(f"Exact matches: {correct}")
    print(f"Type matches: {type_ok}")
    print(f"Path matches: {path_ok}")
    print(f"Mismatches: {mismatches}")
    print("Per‑schema accuracy:")
    for sc, m in by_schema.items():
        acc = (m.get("exact", 0) / m.get("total", 1)) * 100
        print(f"  {sc}: {m.get('exact',0)}/{m.get('total',0)} = {acc:.1f}%")


if __name__ == "__main__":
    main()




