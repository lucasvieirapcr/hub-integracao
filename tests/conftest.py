"""Fixtures compartilhadas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from simulator.activity import ActivityGenerator
from simulator.master_data import MasterData, build_master_data
from simulator.settings import SimulatorConfig, load_config


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        help="roda os testes de integração (precisa dos containers; zera o ERP para o perfil test)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--integration"):
        return
    skip = pytest.mark.skip(reason="teste de integração: use make test-integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


API_TOKEN = "token-de-teste"
ADMIN_TOKEN = "admin-de-teste"
WEBHOOK_SECRET = "segredo-de-teste"


class FakeClock:
    """Relógio controlado pelo teste (data/hora e relógio monotônico)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        self.seconds = 1_000.0

    def __call__(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.seconds += seconds


@pytest.fixture(scope="session")
def test_config() -> SimulatorConfig:
    return load_config(profile_name="test")


@pytest.fixture(scope="session")
def master(test_config: SimulatorConfig) -> MasterData:
    return build_master_data(test_config)


@pytest.fixture(scope="session")
def generator(master: MasterData) -> ActivityGenerator:
    return ActivityGenerator(master)


@pytest.fixture(scope="session")
def dev_master() -> MasterData:
    """Perfil dev: o histórico dele atravessa um reajuste de preço (abril)."""
    return build_master_data(load_config(profile_name="dev"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def api_settings_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "api_token": API_TOKEN,
        "admin_token": ADMIN_TOKEN,
        "db_path": tmp_path / "api.sqlite3",
        "rate_limit_per_minute": 600,
        "rate_limit_burst": 1000,
        "chaos_config_path": None,
        "chaos_ledger_dir": tmp_path / "chaos",
    }


def auth(token: str = API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
