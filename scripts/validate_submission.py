#!/usr/bin/env python3
"""
Самодостаточный валидатор submission.csv без внешних зависимостей на tests/.

Проверяет:
- Правильную структуру (uid;type;request)
- Соответствие множества uid с data/processed/test.csv
- Валидность HTTP методов в type
- Правильный формат request (должен начинаться с '/')
- Отсутствие пустых значений и дубликатов uid
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, Tuple

import click


VALID_METHODS = {"GET", "POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS"}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        return [row for row in reader]


def validate_submission(submission_path: Path, test_path: Path) -> Tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    stats = {"rows": 0}

    if not submission_path.exists():
        return ["Submission file not found"], stats
    if not test_path.exists():
        return ["Test file not found"], stats

    sub = load_csv(submission_path)
    test = load_csv(test_path)
    stats["rows"] = len(sub)

    # Columns
    required_cols = {"uid", "type", "request"}
    if not sub:
        errors.append("Submission is empty")
    else:
        missing_cols = required_cols - set(sub[0].keys())
        if missing_cols:
            errors.append(f"Missing columns: {', '.join(sorted(missing_cols))}")

    # UID checks
    test_uids = {r.get("uid", "").strip() for r in test if r.get("uid")}
    sub_uids = [r.get("uid", "").strip() for r in sub]
    if len(set(sub_uids)) != len(sub_uids):
        errors.append("Duplicate uid entries in submission")
    missing = test_uids - set(sub_uids)
    if missing:
        errors.append(f"Missing {len(missing)} uid from test.csv")
    extra = set(sub_uids) - test_uids
    if extra:
        errors.append(f"Found {len(extra)} extra uid not in test.csv")

    # Row-level checks
    empty_type = 0
    empty_request = 0
    invalid_method = 0
    invalid_path = 0
    for r in sub:
        t = r.get("type", "").strip()
        q = r.get("request", "").strip()
        if not t:
            empty_type += 1
        if not q:
            empty_request += 1
        if t and t not in VALID_METHODS:
            invalid_method += 1
        if q and not q.startswith("/"):
            invalid_path += 1

    if empty_type:
        errors.append(f"Empty 'type' in {empty_type} rows")
    if empty_request:
        errors.append(f"Empty 'request' in {empty_request} rows")
    if invalid_method:
        errors.append(f"Invalid HTTP method in {invalid_method} rows")
    if invalid_path:
        errors.append(f"Invalid API path in {invalid_path} rows (must start with /)")

    return errors, stats


@click.command()
@click.option(
    "--file",
    "-f",
    "submission_file",
    type=click.Path(exists=True),
    help="Путь к submission.csv (по умолчанию: data/processed/submission.csv)",
)
@click.option(
    "--test-file",
    type=click.Path(exists=True),
    default="data/processed/test.csv",
    show_default=True,
    help="Путь к test.csv",
)
def main(submission_file: Optional[str], test_file: str) -> int:
    sub_path = Path(submission_file or "data/processed/submission.csv")
    test_path = Path(test_file)

    click.echo("🚀 Валидация submission файла...")
    click.echo(f"📁 Submission: {sub_path}")
    click.echo(f"📖 Test: {test_path}")
    click.echo("=" * 50)

    errors, stats = validate_submission(sub_path, test_path)
    if errors:
        for e in errors:
            click.echo(f"❌ {e}")
        click.echo("=" * 50)
        click.echo("⚠️  Найдены ошибки валидации. Исправьте их перед отправкой.")
        return 1

    click.echo(f"✅ Rows: {stats.get('rows', 0)}")
    click.echo("🎉 Submission файл валиден.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
