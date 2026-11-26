"""Configuração do simulador quando roda na máquina (fora dos containers). Lê o .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class HostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    oracle_host: str = "localhost"
    oracle_port: int = 1521
    oracle_service: str = "FREEPDB1"
    erp_db_user: str = "erp"
    erp_db_password: SecretStr = SecretStr("")

    sim_admin_token: SecretStr = SecretStr("")
    b2b_base_url: str = "http://localhost:8001"
    crm_base_url: str = "http://localhost:8002"
    payments_base_url: str = "http://localhost:8003"
    b2b_api_token: SecretStr = SecretStr("")
    crm_api_token: SecretStr = SecretStr("")
    payments_api_token: SecretStr = SecretStr("")

    sftp_host: str = "localhost"
    sftp_port: int = 2222
    sftp_user: str = "fornecedor"
    sftp_password: SecretStr = SecretStr("")

    chaos_config_path: Path | None = Path("simulator/chaos.yaml")
    chaos_ledger_dir: Path | None = Path("data/chaos")

    @property
    def oracle_dsn(self) -> str:
        return f"{self.oracle_host}:{self.oracle_port}/{self.oracle_service}"
