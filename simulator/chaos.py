"""Configuração do caos (chaos.yaml) e registro das falhas injetadas, um JSONL por sistema."""

from __future__ import annotations

import json
import random
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ChaosRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    probability: float = Field(default=0.0, ge=0.0, le=1.0)

    def fires(self, rng: random.Random) -> bool:
        return self.enabled and rng.random() < self.probability


class LatencyRule(ChaosRule):
    min_ms: int = Field(default=0, ge=0)
    max_ms: int = Field(default=0, ge=0)


class InvalidRowsRule(ChaosRule):
    max_rows: int = Field(default=5, ge=1)


class ApiChaos(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    latency: LatencyRule = LatencyRule()
    outage: ChaosRule = ChaosRule()
    duplicate_events: ChaosRule = ChaosRule()
    out_of_order: ChaosRule = ChaosRule()


class SupplierFileChaos(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    late: ChaosRule = ChaosRule()
    renamed_column: ChaosRule = ChaosRule()
    wrong_encoding: ChaosRule = ChaosRule()
    invalid_rows: InvalidRowsRule = InvalidRowsRule()


class ErpChaos(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    b2b_replication_gap: ChaosRule = ChaosRule()


class ChaosConfig(BaseModel):
    """Sem arquivo, tudo desligado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int = 0
    b2b_store: ApiChaos = ApiChaos()
    crm: ApiChaos = ApiChaos()
    payments: ApiChaos = ApiChaos()
    supplier_file: SupplierFileChaos = SupplierFileChaos()
    erp: ErpChaos = ErpChaos()


def load_chaos_config(path: Path | None) -> ChaosConfig:
    if path is None or not path.exists():
        return ChaosConfig()
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ChaosConfig.model_validate(raw)


class ChaosLedger:
    """Registro das falhas injetadas. Sem diretório, não grava."""

    def __init__(self, directory: Path | None, system: str) -> None:
        self.system = system
        self.path = directory / f"{system}.jsonl" if directory else None
        self._lock = threading.Lock()

    def record(self, kind: str, **detail: Any) -> None:
        if self.path is None:
            return
        line = {
            "injected_at": datetime.now(UTC).isoformat(),
            "system": self.system,
            "kind": kind,
            "detail": detail,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
