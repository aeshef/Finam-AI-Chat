from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass
class EndpointDef:
    schema: str
    method: str
    path: str
    params: Dict[str, str]
    json_from: Optional[str] = None


class EndpointRegistry:
    def __init__(self, config_path: str = "configs/endpoints.yaml", extra_catalogs: Optional[list[str]] = None) -> None:
        self.config_path = config_path
        self.extra_catalogs = extra_catalogs or ["configs/endpoints.generated.yaml"]
        self._mtime: Optional[Any] = None
        self._by_schema: Dict[str, EndpointDef] = {}
        self._items: List[dict] = []
        self._load()

    def _load(self) -> None:
        mtime = os.path.getmtime(self.config_path)
        extra_mtimes = []
        for p in self.extra_catalogs:
            try:
                extra_mtimes.append(os.path.getmtime(p))
            except Exception:
                extra_mtimes.append(None)
        state = (mtime, tuple(extra_mtimes))
        if self._mtime is not None and self._mtime == state:
            return
        with open(self.config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        items = list(cfg.get("endpoints", []))
        # Merge generated catalogs (if exist)
        for p in self.extra_catalogs:
            try:
                with open(p, encoding="utf-8") as ef:
                    extra = yaml.safe_load(ef) or {}
                for it in extra.get("endpoints", []) or []:
                    items.append(it)
            except Exception:
                continue
        self._by_schema.clear()
        self._items = items
        for item in self._items:
            ed = EndpointDef(
                schema=item["schema"],
                method=item["method"],
                path=item["path"],
                params=item.get("params", {}) or {},
                json_from=item.get("json_from"),
            )
            self._by_schema[ed.schema] = ed
        self._mtime = state

    def list_items(self) -> List[dict]:
        self._load()
        return list(self._items)

    def get_definition(self, schema_name: str) -> Optional[EndpointDef]:
        self._load()
        return self._by_schema.get(schema_name)

    def required_slots(self, schema_name: str) -> List[str]:
        """Return slot names that are required by path/params templates."""
        self._load()
        ed = self._by_schema.get(schema_name)
        if not ed:
            return []
        required: List[str] = []
        # path placeholders are required
        for seg in _extract_placeholders(ed.path):
            field, _ = _parse_placeholder(seg)
            if field not in required:
                required.append(field)
        # params: only non-optional placeholders
        for _, tmpl in (ed.params or {}).items():
            if isinstance(tmpl, str) and tmpl.startswith("{") and tmpl.endswith("}"):
                inner = tmpl[1:-1]
                field, optional = _parse_placeholder(inner)
                if not optional and field not in required:
                    required.append(field)
        return required

    def resolve(self, schema_obj: Any) -> Tuple[str, str, Dict[str, Any]]:
        self._load()
        schema_name = type(schema_obj).__name__
        if schema_name not in self._by_schema:
            raise ValueError(f"Schema {schema_name} not in registry")
        ed = self._by_schema[schema_name]
        # Substitute path placeholders
        path = _substitute(ed.path, schema_obj)
        # Build params dict from template
        params: Dict[str, Any] = {}
        for k, v in (ed.params or {}).items():
            val = _template_value(v, schema_obj)
            if val is not _MISSING:
                params[k] = val
        if ed.json_from:
            obj = getattr(schema_obj, ed.json_from, None)
            if obj is not None and hasattr(obj, "model_dump"):
                params["json"] = obj.model_dump()
        return ed.method, path, params

    def classify_path(self, path: str) -> Optional[str]:
        """Return schema name whose template matches given path (best-effort)."""
        self._load()
        for it in self._items:
            tpl = it.get("path")
            if not isinstance(tpl, str):
                continue
            pattern = _template_to_regex(tpl)
            import re as _re

            if _re.fullmatch(pattern, path):
                return it.get("schema")
        return None


_MISSING = object()


def _substitute(template: str, schema_obj: Any) -> str:
    out = template
    for seg in _extract_placeholders(template):
        field, _ = _parse_placeholder(seg)
        val = getattr(schema_obj, field, None)
        if val is None:
            raise ValueError(f"Missing required field {field} for path template")
        out = out.replace("{" + seg + "}", str(val))
    return out


def _template_value(template: str, schema_obj: Any):
    # e.g., "{start?}" or "{timeframe}"
    if not template.startswith("{") or not template.endswith("}"):
        return template
    inner = template[1:-1]
    field, optional = _parse_placeholder(inner)
    val = getattr(schema_obj, field, None)
    if val is None:
        return _MISSING if not optional else _MISSING
    return val


def _extract_placeholders(s: str) -> List[str]:
    segs: List[str] = []
    i = 0
    while i < len(s):
        if s[i] == "{":
            j = s.find("}", i + 1)
            if j == -1:
                break
            segs.append(s[i + 1 : j])
            i = j + 1
        else:
            i += 1
    return segs


def _parse_placeholder(seg: str) -> Tuple[str, bool]:
    # "field" or "field?"
    if seg.endswith("?"):
        return seg[:-1], True
    return seg, False


def _template_to_regex(template: str) -> str:
    """Convert a path template with placeholders to a regex.

    Example: /v1/instruments/{symbol}/bars -> ^/v1/instruments/[^/]+/bars(?:\?.*)?$.
    """
    import re as _re

    pattern_parts: list[str] = []
    i = 0
    while i < len(template):
        if template[i] == "{":
            j = template.find("}", i + 1)
            if j == -1:
                # unmatched brace, escape the rest
                pattern_parts.append(_re.escape(template[i:]))
                break
            # placeholder -> one path segment
            pattern_parts.append("([^/]+)")
            i = j + 1
        else:
            # collect literal until next '{'
            k = template.find("{", i)
            if k == -1:
                lit = template[i:]
                i = len(template)
            else:
                lit = template[i:k]
                i = k
            pattern_parts.append(_re.escape(lit))

    body_regex = "".join(pattern_parts)
    return "^" + body_regex + r"(?:\?.*)?$"


