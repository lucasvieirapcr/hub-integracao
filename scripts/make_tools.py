"""Utilitários do Makefile.

help              lista os alvos
confirm "texto"   pede confirmação ('sim')
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"
TARGET = re.compile(r"^([a-zA-Z_-]+):.*?## (.+)$")


def show_help() -> int:
    print("Comandos disponíveis (make <comando>):")
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = TARGET.match(line)
        if match:
            print(f"  {match.group(1):<18} {match.group(2)}")
    return 0


def confirm(message: str) -> int:
    answer = input(f"{message} Digite 'sim' para continuar: ").strip().lower()
    if answer == "sim":
        return 0
    print("Cancelado.")
    return 1


def main(argv: list[str]) -> int:
    if argv[:1] == ["help"]:
        return show_help()
    if argv[:1] == ["confirm"] and len(argv) == 2:
        return confirm(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
