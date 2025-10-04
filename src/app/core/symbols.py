from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, List
import re as _re
from pathlib import Path

from src.app.core.normalize import infer_market_symbol
from src.app.core.llm import call_llm


@dataclass
class SymbolResolutionConfig:
    strategies: Sequence[str]
    default_market: str = "MISX"
    aliases_path: str = "configs/aliases.yaml"
    local_assets_path: Optional[str] = None  # optional CSV with known symbols


class SymbolResolver:
    def __init__(self, config: Optional[SymbolResolutionConfig] = None) -> None:
        if config is None:
            config = SymbolResolutionConfig(
                strategies=(
                    "aliases",
                    "pattern",
                    # "local_assets",  # enable when cache is available
                    # "llm",           # enable in interactive modes
                )
            )
        self.config = config
        self._asset_cache: Optional[List[Dict[str, Any]]] = None

    def resolve(self, question: str, context: Optional[Dict[str, Any]] = None, allow_llm: bool = False) -> Optional[str]:
        ctx = context or {}
        # 0) context override
        sym = ctx.get("symbol")
        if isinstance(sym, str) and sym.strip():
            return infer_market_symbol(sym)

        for strat in self.config.strategies:
            if strat == "pattern":
                s = self._from_pattern(question)
                if s:
                    return infer_market_symbol(s)
            elif strat == "aliases":
                s = self._from_alias(question)
                if s:
                    return infer_market_symbol(s)
            elif strat == "local_assets":
                s = self._from_local_assets(question)
                if s:
                    return infer_market_symbol(s)
            elif strat == "live_assets":
                s = self._from_live_assets(question)
                if s:
                    return infer_market_symbol(s)
            elif strat == "llm" and allow_llm:
                s = self._from_llm(question)
                if s:
                    return infer_market_symbol(s)
        return None

    def _from_pattern(self, text: str) -> Optional[str]:
        # TICKER or TICKER@MARKET (preserve original case)
        stop = {"ISIN"}
        m = _re.search(r"\b([A-Za-z0-9]{2,12}(?:@[A-Za-z]{2,8})?)\b", text)
        if not m:
            return None
        token = m.group(1)
        if token.upper() in stop:
            return None
        # skip order ids and pure digits/years mistaken for symbols
        if _re.fullmatch(r"ORD\d+", token.upper()):
            return None
        if _re.fullmatch(r"\d{2,4}", token):
            return None
        # ensure at least one letter
        if not _re.search(r"[A-Za-z]", token):
            return None
        return token

    def _from_alias(self, text: str) -> Optional[str]:
        try:
            import yaml  # type: ignore
        except Exception:
            return None
        path = Path(self.config.aliases_path)
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            aliases: Dict[str, str] = {k.lower(): v for k, v in (cfg.get("instrument_aliases") or {}).items()}
        except Exception:
            return None
        low = text.lower()
        # longest alias first
        for key in sorted(aliases.keys(), key=len, reverse=True):
            if key in low:
                return aliases[key]
        return None

    def _from_local_assets(self, text: str) -> Optional[str]:
        path_str = self.config.local_assets_path
        if not path_str:
            return None
        path = Path(path_str)
        if not path.exists():
            return None
        low = text.lower()
        try:
            import csv

            with open(path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                best: Optional[str] = None
                for row in reader:
                    name = (row.get("name") or row.get("shortname") or "").lower()
                    symbol = (row.get("symbol") or row.get("ticker") or "").strip()
                    if not symbol:
                        continue
                    if name and name in low:
                        best = symbol
                        break
                return best
        except Exception:
            return None

    def _from_llm(self, text: str) -> Optional[str]:
        prompt = (
            "Выдели финансовый инструмент из текста. Верни строго тикер (например, SBER или SBER@MISX).\n"
            "Если явного тикера нет, верни пустую строку.\n\nТекст: "
            + text
        )
        try:
            resp = call_llm([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=10)
            content = resp["choices"][0]["message"]["content"].strip()
            content = content.split()[0]
            if content and _re.fullmatch(r"[A-Z0-9]{2,12}(?:@[A-Z]{2,8})?", content):
                return content
            return None
        except Exception:
            return None

    def _ensure_live_assets(self) -> None:
        if self._asset_cache is not None:
            return
        try:
            # Multi-source discovery with graceful fallback, no hardcoding symbols
            assets: List[Dict[str, Any]] = []
            # 1) From train/test questions (instrument-like tokens)
            import csv
            from pathlib import Path as _Path
            train_path = _Path("data/processed/train.csv")
            for p in [train_path]:
                if p.exists():
                    with open(p, encoding="utf-8") as f:
                        r = csv.DictReader(f, delimiter=";")
                        for row in r:
                            q = (row.get("question") or "").strip()
                            for tok in set(_re.findall(r"\b[A-Z0-9]{2,12}(?:@[A-Z]{2,8})?\b", q.upper())):
                                if _re.fullmatch(r"ORD\d+", tok):
                                    continue
                                if tok.isdigit():
                                    continue
                                assets.append({"symbol": tok})
            # 2) From generated endpoint catalog names (rare but cheap)
            try:
                import yaml as _yaml
                gen = _Path("configs/endpoints.generated.yaml")
                if gen.exists():
                    cfg = _yaml.safe_load(gen.read_text(encoding="utf-8")) or {}
                    for it in cfg.get("endpoints", []) or []:
                        name = (it.get("schema") or "").upper()
                        for tok in set(_re.findall(r"[A-Z]{3,6}@[A-Z]{2,6}", name)):
                            assets.append({"symbol": tok})
            except Exception:
                pass
            # dedupe
            seen = set()
            uniq: List[Dict[str, Any]] = []
            for a in assets:
                s = a.get("symbol")
                if not s:
                    continue
                if s in seen:
                    continue
                seen.add(s)
                uniq.append(a)
            self._asset_cache = uniq
        except Exception:
            self._asset_cache = []

    def _from_live_assets(self, text: str) -> Optional[str]:
        # Try to use live asset cache when available (non-blocking, optional)
        self._ensure_live_assets()
        if not self._asset_cache:
            return None
        low = text.lower()
        for row in self._asset_cache:
            name = (row.get("name") or row.get("shortname") or "").lower()
            symbol = (row.get("symbol") or row.get("ticker") or "").strip()
            if name and name in low and symbol:
                return symbol
        return None


