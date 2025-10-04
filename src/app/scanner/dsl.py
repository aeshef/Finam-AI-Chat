from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.scanner.scan import ScanResult, run_scan, ScanCriteria


@dataclass
class FilterSpec:
    name: str
    value: Any


@dataclass
class SortSpec:
    key: str  # growth_pct | total_volume
    descending: bool = True


@dataclass
class ScreenSpec:
    symbols: List[str]
    timeframe: str
    start: str
    end: str
    filters: List[FilterSpec]
    sorts: List[SortSpec]
    require_short: bool = False
    account_id: Optional[str] = None


def _apply_sorts(results: List[ScanResult], sorts: List[SortSpec]) -> List[ScanResult]:
    if not sorts:
        return results
    # support single sort primary; use safe numeric key (avoid None comparisons)
    s = sorts[0]
    def safe_key(r: ScanResult):
        v = getattr(r, s.key, None)
        try:
            return float(v) if v is not None else float("-inf")
        except Exception:
            return float("-inf")
    return sorted(results, key=safe_key, reverse=s.descending)


def run_screen(router: ToolRouter, spec: ScreenSpec, page: int = 1, page_size: int = 50) -> Tuple[List[ScanResult], Dict[str, Any]]:
    # Translate filters to ScanCriteria; keep generic
    min_growth: Optional[float] = None
    min_volume: Optional[float] = None
    for f in spec.filters:
        if f.name in ("min_growth_pct", "growth_pct_min"):
            try:
                min_growth = float(f.value)
            except Exception:
                pass
        if f.name in ("min_volume", "volume_min"):
            try:
                min_volume = float(f.value)
            except Exception:
                pass

    criteria = ScanCriteria(
        symbols=spec.symbols,
        timeframe=spec.timeframe,
        start=spec.start,
        end=spec.end,
        min_growth_pct=min_growth,
        min_volume=min_volume,
        require_short=spec.require_short,
        account_id=spec.account_id,  # type: ignore[arg-type]
    )

    all_results = run_scan(router, criteria)
    all_results = _apply_sorts(all_results, spec.sorts)

    # Pagination
    total = len(all_results)
    start_idx = max(0, (page - 1) * page_size)
    end_idx = min(total, start_idx + page_size)
    page_items = all_results[start_idx:end_idx]
    meta = {"total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}
    return page_items, meta


