#!/usr/bin/env python3
import csv
import sys
from pathlib import Path


def main(test_file: str, submission_file: str, output_file: str) -> None:
    test_path = Path(test_file)
    sub_path = Path(submission_file)
    out_path = Path(output_file)

    with open(test_path, encoding="utf-8") as ft:
        test_rows = list(csv.DictReader(ft, delimiter=";"))

    by_uid: dict[str, dict[str, str]] = {}
    with open(sub_path, encoding="utf-8") as fs:
        for row in csv.DictReader(fs, delimiter=";"):
            by_uid[row["uid"]] = row

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fo:
        fieldnames = ["uid", "question", "my_type", "my_request"]
        w = csv.DictWriter(fo, fieldnames=fieldnames, delimiter=";", lineterminator="\n")
        w.writeheader()
        for r in test_rows:
            sub = by_uid.get(r["uid"], {})
            w.writerow({
                "uid": r["uid"],
                "question": r.get("question", ""),
                "my_type": sub.get("type", ""),
                "my_request": sub.get("request", ""),
            })


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: merge_predictions.py TEST_CSV SUBMISSION_CSV OUTPUT_CSV", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])


