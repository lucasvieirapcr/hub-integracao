"""CLI do simulador: info, seed, simulate e supplier-file."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from simulator.activity import ActivityGenerator
from simulator.chaos import ChaosConfig, ChaosLedger, load_chaos_config
from simulator.erp_loader import connect, seed_erp
from simulator.erp_simulation import next_simulation_day, simulate_erp_day
from simulator.host_settings import HostSettings
from simulator.master_data import MasterData, build_master_data
from simulator.settings import load_config
from simulator.sftp_upload import SftpSettings, upload_file
from simulator.sources_client import SourceSystemsClient, seed_source_systems
from simulator.supplier_file import build_supplier_file

TARGETS = ("erp", "apis", "sftp")


def _erp_connection(settings: HostSettings) -> Any:
    return connect(
        settings.erp_db_user, settings.erp_db_password.get_secret_value(), settings.oracle_dsn
    )


def _send_supplier_file(
    settings: HostSettings,
    master: MasterData,
    day: date,
    chaos: ChaosConfig,
    *,
    force: bool = False,
) -> None:
    supplier = build_supplier_file(master, day, chaos.supplier_file, chaos.seed)
    ledger = ChaosLedger(settings.chaos_ledger_dir, "supplier_file")
    for injection in supplier.injected:
        ledger.record(
            injection["kind"],
            file=supplier.file_name,
            **{k: v for k, v in injection.items() if k != "kind"},
        )
    if supplier.late and not force:
        print(
            f"SFTP: {supplier.file_name} atrasado de propósito (caos); envie depois com supplier-file --force"
        )
        return
    sftp = SftpSettings(
        settings.sftp_host,
        settings.sftp_port,
        settings.sftp_user,
        settings.sftp_password.get_secret_value(),
    )
    path = upload_file(sftp, supplier.file_name, supplier.content)
    print(f"SFTP: {path} enviado ({supplier.row_count} linhas, {supplier.encoding})")


def cmd_info(args: argparse.Namespace) -> int:
    cfg = load_config(profile_name=args.profile)
    p = cfg.profile
    span = (cfg.history_end - cfg.history_start).days + 1
    print(
        f"Perfil {cfg.profile_name} | seed {cfg.seed} | histórico {cfg.history_start} a {cfg.history_end} ({span} dias)"
    )
    print(f"Clientes {p.customers} | produtos {p.products} | CDs {p.warehouses}")
    print(
        f"Pedidos/dia (base): ERP {p.erp_orders_per_day}, B2B {p.b2b_orders_per_day} "
        f"| itens por pedido {p.items_per_order[0]}-{p.items_per_order[1]}"
    )
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    settings = HostSettings()
    cfg = load_config(profile_name=args.profile)
    master = build_master_data(cfg)
    generator = ActivityGenerator(master)
    targets = set(args.only or TARGETS)
    print(f"Perfil {cfg.profile_name}: histórico de {cfg.history_start} a {cfg.history_end}")

    if "erp" in targets:
        with _erp_connection(settings) as conn:
            seed_erp(conn, master, generator)
    if "apis" in targets:
        seed_source_systems(SourceSystemsClient(settings), master, generator)
    if "sftp" in targets:
        # Arquivo do último dia do histórico, sem caos: o ponto de partida é sempre limpo.
        _send_supplier_file(settings, master, cfg.history_end, ChaosConfig())
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    settings = HostSettings()
    cfg = load_config(profile_name=args.profile)
    master = build_master_data(cfg)
    generator = ActivityGenerator(master)
    chaos = load_chaos_config(settings.chaos_config_path)
    erp_ledger = ChaosLedger(settings.chaos_ledger_dir, "erp")
    client = SourceSystemsClient(settings)

    with _erp_connection(settings) as conn:
        start = args.date or next_simulation_day(conn, cfg.history_end)
        for offset in range(args.days):
            day = start + timedelta(days=offset)
            activity = generator.day(day)
            erp = simulate_erp_day(conn, master, activity, chaos.erp, chaos.seed, erp_ledger)
            if erp.skipped:
                print(f"{day} ERP: dia já simulado, nada a fazer")
            else:
                print(
                    f"{day} ERP: {erp.created} pedidos, {erp.invoiced} faturados, {erp.cancelled} cancelados, "
                    f"{erp.out_of_stock} sem estoque, {erp.replenishments} entradas de estoque"
                )
            client.push_b2b_orders(activity.b2b_orders)
            paid = client.push_payments(activity.payments, enqueue_webhooks=True)
            crm = client.push_crm_changes(activity.crm_changes, enqueue_webhooks=True)
            delivery = client.deliver_webhooks()
            print(
                f"{day} APIs: {len(activity.b2b_orders)} pedidos B2B; eventos novos na outbox: "
                f"{paid} pagamentos, {crm} CRM; entregues agora: "
                f"{delivery['payments']['delivered']} pagamentos, {delivery['crm']['delivered']} CRM"
            )
            _send_supplier_file(settings, master, day, chaos)
    return 0


def cmd_supplier_file(args: argparse.Namespace) -> int:
    settings = HostSettings()
    cfg = load_config(profile_name=args.profile)
    master = build_master_data(cfg)
    chaos = load_chaos_config(settings.chaos_config_path)
    if args.output:
        supplier = build_supplier_file(master, args.date, chaos.supplier_file, chaos.seed)
        target = Path(args.output) / supplier.file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(supplier.content)
        print(f"Arquivo gravado em {target} ({supplier.row_count} linhas)")
        return 0
    _send_supplier_file(settings, master, args.date, chaos, force=args.force)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simulator", description="Simulador da Distribuidora Exemplo"
    )
    parser.add_argument("--profile", help="perfil do config.yaml (padrão: SIM_PROFILE ou dev)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="mostra os volumes do perfil").set_defaults(func=cmd_info)

    seed = sub.add_parser("seed", help="carga histórica (zera e recarrega; idempotente)")
    seed.add_argument("--only", nargs="+", choices=TARGETS, help="carrega só os destinos indicados")
    seed.set_defaults(func=cmd_seed)

    simulate = sub.add_parser("simulate", help="simula os próximos dias de operação")
    simulate.add_argument(
        "--date", type=date.fromisoformat, help="primeiro dia (padrão: o seguinte ao último)"
    )
    simulate.add_argument("--days", type=int, default=1, help="quantos dias simular (padrão: 1)")
    simulate.set_defaults(func=cmd_simulate)

    supplier = sub.add_parser("supplier-file", help="gera o CSV do fornecedor de um dia")
    supplier.add_argument("--date", type=date.fromisoformat, required=True)
    supplier.add_argument("--output", help="grava numa pasta local em vez de enviar por SFTP")
    supplier.add_argument(
        "--force", action="store_true", help="envia mesmo se o caos marcou atraso"
    )
    supplier.set_defaults(func=cmd_supplier_file)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
