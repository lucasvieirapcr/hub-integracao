"""Envio do arquivo do fornecedor para o servidor SFTP (papel do fornecedor)."""

from __future__ import annotations

import io
from dataclasses import dataclass

import paramiko

REMOTE_DIR = "inbox"


@dataclass(frozen=True, slots=True)
class SftpSettings:
    host: str
    port: int
    user: str
    password: str


def upload_file(settings: SftpSettings, file_name: str, content: bytes) -> str:
    """Envia gravando em arquivo temporário e renomeando no final."""
    client = paramiko.SSHClient()
    # Servidor local: a chave do host muda a cada recriação do container.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507
    client.connect(
        settings.host,
        port=settings.port,
        username=settings.user,
        password=settings.password,
        look_for_keys=False,
        allow_agent=False,
        timeout=15,
    )
    try:
        sftp = client.open_sftp()
        final_path = f"{REMOTE_DIR}/{file_name}"
        temp_path = f"{REMOTE_DIR}/.{file_name}.part"
        sftp.putfo(io.BytesIO(content), temp_path)
        sftp.posix_rename(temp_path, final_path)
        return final_path
    finally:
        client.close()
