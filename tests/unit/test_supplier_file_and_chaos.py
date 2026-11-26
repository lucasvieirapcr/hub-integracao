"""Arquivo do fornecedor, caos controlado e gabarito."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

from simulator.chaos import (
    ChaosLedger,
    ChaosRule,
    InvalidRowsRule,
    SupplierFileChaos,
    load_chaos_config,
)
from simulator.master_data import MasterData
from simulator.supplier_file import COLUMNS, build_supplier_file

DAY = date(2026, 10, 20)
ALWAYS = ChaosRule(enabled=True, probability=1.0)


def _parse(content: bytes, encoding: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode(encoding)), delimiter=";"))


def test_clean_file_has_expected_layout(master: MasterData) -> None:
    supplier = build_supplier_file(master, DAY, SupplierFileChaos())
    rows = _parse(supplier.content, "utf-8")
    assert supplier.file_name == "fornecedor_20261020.csv"
    assert rows[0] == list(COLUMNS)
    assert len(rows) - 1 == supplier.row_count > 0
    assert supplier.injected == []
    assert not supplier.late
    assert b"\r\n" in supplier.content  # quebra de linha de sistema legado


def test_file_is_deterministic(master: MasterData) -> None:
    first = build_supplier_file(master, DAY, SupplierFileChaos())
    second = build_supplier_file(master, DAY, SupplierFileChaos())
    assert first.content == second.content


def test_chaos_injects_every_problem_and_reports_it(master: MasterData) -> None:
    chaos = SupplierFileChaos(
        late=ALWAYS,
        renamed_column=ALWAYS,
        wrong_encoding=ALWAYS,
        invalid_rows=InvalidRowsRule(enabled=True, probability=1.0, max_rows=3),
    )
    clean = _parse(build_supplier_file(master, DAY, SupplierFileChaos()).content, "utf-8")
    dirty_file = build_supplier_file(master, DAY, chaos, chaos_seed=42)
    dirty = _parse(dirty_file.content, "cp1252")

    kinds = {item["kind"] for item in dirty_file.injected}
    assert kinds == {"renamed_column", "invalid_row", "wrong_encoding", "late_file"}
    assert dirty_file.late
    assert dirty_file.encoding == "cp1252"
    assert dirty[0] != clean[0]  # cabeçalho com coluna renomeada

    # Só as linhas registradas no gabarito mudaram; o resto do arquivo é idêntico.
    broken_lines = {item["line"] for item in dirty_file.injected if item["kind"] == "invalid_row"}
    for line_number in range(2, len(clean) + 1):
        if line_number not in broken_lines:
            assert dirty[line_number - 1] == clean[line_number - 1]


def test_chaos_file_in_repo_is_all_disabled() -> None:
    config = load_chaos_config(Path("simulator/chaos.yaml"))
    rules = [
        *config.b2b_store.model_dump().values(),
        *config.crm.model_dump().values(),
        *config.payments.model_dump().values(),
        *config.supplier_file.model_dump().values(),
        *config.erp.model_dump().values(),
    ]
    assert rules
    assert not any(rule["enabled"] for rule in rules)


def test_missing_chaos_file_means_no_chaos(tmp_path: Path) -> None:
    config = load_chaos_config(tmp_path / "nao_existe.yaml")
    assert not config.crm.duplicate_events.enabled


def test_ledger_writes_one_json_line_per_injection(tmp_path: Path) -> None:
    ledger = ChaosLedger(tmp_path, "crm")
    ledger.record("duplicate_event", event_id="abc")
    ledger.record("outage", status_code=503)
    lines = [json.loads(line) for line in (tmp_path / "crm.jsonl").read_text("utf-8").splitlines()]
    assert [line["kind"] for line in lines] == ["duplicate_event", "outage"]
    assert lines[0]["detail"] == {"event_id": "abc"}
    assert all(line["system"] == "crm" and line["injected_at"] for line in lines)
