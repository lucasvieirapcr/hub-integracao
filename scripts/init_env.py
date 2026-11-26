"""Gera o .env a partir do .env.example, preenchendo senhas e tokens vazios. Não sobrescreve valores."""

from __future__ import annotations

import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_SUFFIXES = ("PASSWORD", "TOKEN", "SECRET")
ALPHABET = string.ascii_letters + string.digits


def random_secret(length: int = 24) -> str:
    # alfanumérico começando com letra: dispensa aspas no Oracle e no shell
    return secrets.choice(string.ascii_letters) + "".join(
        secrets.choice(ALPHABET) for _ in range(length - 1)
    )


def parse(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    example_lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    env_path = ROOT / ".env"
    existing = parse(env_path.read_text(encoding="utf-8").splitlines()) if env_path.exists() else {}

    output: list[str] = []
    generated: list[str] = []
    added: list[str] = []
    for line in example_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key, _, default = line.partition("=")
        key = key.strip()
        if key in existing:
            value = existing[key]
        else:
            value = default.strip()
            if not value and key.endswith(SECRET_SUFFIXES):
                value = random_secret()
                generated.append(key)
            added.append(key)
        output.append(f"{key}={value}")
    # Preserva chaves que só existem no .env local.
    for key, value in existing.items():
        if key not in parse(example_lines):
            output.append(f"{key}={value}")

    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f".env atualizado: {len(added)} chave(s) nova(s), {len(generated)} segredo(s) gerado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
