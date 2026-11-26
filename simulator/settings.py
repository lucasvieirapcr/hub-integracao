"""Leitura do simulator/config.yaml e escolha do perfil de volume."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")
DEFAULT_PROFILE = "dev"


class Profile(BaseModel):
    """Volumes de um perfil."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    history_start: date
    customers: int = Field(gt=0)
    products: int = Field(gt=0)
    warehouses: int = Field(ge=1, le=5)
    erp_orders_per_day: int = Field(ge=0)
    b2b_orders_per_day: int = Field(ge=0)
    items_per_order: tuple[int, int]
    crm_events_per_day: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_items_range(self) -> Profile:
        low, high = self.items_per_order
        if not 1 <= low <= high:
            raise ValueError("items_per_order deve ser [mínimo, máximo] com 1 <= mínimo <= máximo")
        return self


class SimulatorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int
    history_end: date
    profile_name: str
    profile: Profile

    @model_validator(mode="after")
    def _check_dates(self) -> SimulatorConfig:
        if self.profile.history_start > self.history_end:
            raise ValueError("history_start precisa ser anterior a history_end")
        return self

    @property
    def history_start(self) -> date:
        return self.profile.history_start


def load_config(
    path: Path = DEFAULT_CONFIG_PATH, profile_name: str | None = None
) -> SimulatorConfig:
    """Carrega o YAML e seleciona o perfil (argumento > SIM_PROFILE > 'dev')."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    name = profile_name or os.environ.get("SIM_PROFILE") or DEFAULT_PROFILE
    profiles: dict[str, Any] = raw["profiles"]
    if name not in profiles:
        raise ValueError(f"Perfil '{name}' não existe em {path}. Opções: {sorted(profiles)}")
    return SimulatorConfig(
        seed=raw["seed"],
        history_end=raw["history_end"],
        profile_name=name,
        profile=Profile.model_validate(profiles[name]),
    )
