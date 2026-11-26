"""Configuração das APIs simuladas via variáveis de ambiente (prefixos B2B_, CRM_ e PAYMENTS_)."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    api_token: SecretStr
    admin_token: SecretStr = Field(validation_alias=AliasChoices("SIM_ADMIN_TOKEN", "admin_token"))
    db_path: Path
    rate_limit_per_minute: int = Field(default=60, gt=0)
    rate_limit_burst: int = Field(default=10, gt=0)
    max_page_size: int = Field(default=500, gt=0)
    chaos_config_path: Path | None = Field(
        default=None, validation_alias=AliasChoices("CHAOS_CONFIG_PATH", "chaos_config_path")
    )
    chaos_ledger_dir: Path | None = Field(
        default=None, validation_alias=AliasChoices("CHAOS_LEDGER_DIR", "chaos_ledger_dir")
    )


class WebhookSettings(ApiSettings):
    webhook_secret: SecretStr
    webhook_url: str = ""  # vazio = eventos aguardam na outbox
    webhook_max_attempts: int = Field(default=8, gt=0)
    webhook_interval_seconds: float = Field(default=5.0, gt=0)


class B2bSettings(ApiSettings):
    model_config = SettingsConfigDict(env_prefix="B2B_", extra="ignore", populate_by_name=True)


class CrmSettings(WebhookSettings):
    model_config = SettingsConfigDict(env_prefix="CRM_", extra="ignore", populate_by_name=True)


class PaymentsSettings(WebhookSettings):
    model_config = SettingsConfigDict(env_prefix="PAYMENTS_", extra="ignore", populate_by_name=True)
