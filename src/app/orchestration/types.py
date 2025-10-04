from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class OrchestrationContext:
    dry_run: bool = True
    account_id: Optional[str] = None
    confirm: bool = False


@dataclass
class OrchestrationResult:
    disambiguation: bool = False
    requires_confirmation: bool = False
    message: Optional[str] = None
    api: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    insights: Optional[Dict[str, Any]] = None
    suggestions: Optional[str] = None
    trace: Optional[List[Dict[str, Any]]] = None



