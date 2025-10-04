#!/usr/bin/env python3
from __future__ import annotations

"""
Generate a normalized endpoint catalog YAML from a Postman collection (JSON) or minimal REST spec.
This avoids hardcoding: we can refresh endpoints as the API evolves.

Usage:
  python scripts/generate_endpoint_catalog.py --postman path/to/collection.json --out configs/endpoints.generated.yaml
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import yaml


def _extract_items(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for it in node.get("item", []) or []:
        if "item" in it:
            items.extend(_extract_items(it))
        else:
            req = it.get("request") or {}
            method = (req.get("method") or "").upper()
            url = req.get("url") or {}
            path = url.get("path") or []
            if isinstance(path, list):
                p = "/" + "/".join(str(seg) for seg in path)
            else:
                p = str(path)
            if not p.startswith("/"):
                p = "/" + p
            # Normalize Finam-style variable names if possible
            # Replace :var or {{var}} or :account_id with template placeholders
            p = p.replace(":account_id", "{account_id}").replace(":order_id", "{order_id}")
            name = it.get("name") or p
            items.append({
                "name": name,
                "method": method,
                "path": p,
            })
    return items


@click.command()
@click.option("--postman", type=click.Path(exists=False, path_type=Path), required=False, help="Path or URL to Postman collection JSON")
@click.option("--out", type=click.Path(path_type=Path), default=Path("configs/endpoints.generated.yaml"))
def main(postman: Path | None, out: Path) -> None:
    if postman is None:
        raise SystemExit("--postman path or URL is required")
    # Support URL or local file
    text: str
    s = str(postman)
    if s.startswith("http://") or s.startswith("https://"):
        import requests
        resp = requests.get(s, timeout=30)
        resp.raise_for_status()
        text = resp.text
    else:
        text = Path(s).read_text(encoding="utf-8")
    data = json.loads(text)
    root = data
    if isinstance(data, dict) and "item" not in data and data.get("collection"):
        root = data["collection"]
    items = _extract_items(root)

    # Minimal grouping heuristic: map to intents/schemas later via manual curation
    catalog = {"endpoints": []}
    for it in items:
        catalog["endpoints"].append({
            "schema": it["name"].replace(" ", "").replace("/", "_"),
            "method": it["method"],
            "path": "/" + it["path"].lstrip("/"),
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True), encoding="utf-8")
    click.echo(f"Wrote catalog with {len(items)} endpoints to {out}")


if __name__ == "__main__":
    main()


