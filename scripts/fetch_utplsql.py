"""Baixa o utPLSQL (versão fixa), confere o SHA-256 e extrai em .cache/utPLSQL."""

from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

VERSION = "v.3.2.3"
BASE_URL = f"https://github.com/utPLSQL/utPLSQL/releases/download/{VERSION}"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"URL inesperada: {url}")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (URL fixa, https)
        data: bytes = response.read()
        return data


def main() -> int:
    target = CACHE_DIR / "utPLSQL"
    marker = target / ".version"
    if marker.exists() and marker.read_text().strip() == VERSION:
        print(f"utPLSQL {VERSION} já está em {target}")
        return 0

    archive = _download(f"{BASE_URL}/utPLSQL.tar.gz")
    checksum_text = _download(f"{BASE_URL}/utPLSQL.tar.gz.sha256").decode()
    # formatos GNU e BSD
    expected = next(token for token in checksum_text.split() if len(token) == 64).lower()
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        print(f"SHA-256 não confere: esperado {expected}, obtido {actual}", file=sys.stderr)
        return 1

    CACHE_DIR.mkdir(exist_ok=True)
    archive_path = CACHE_DIR / "utPLSQL.tar.gz"
    archive_path.write_bytes(archive)
    if target.exists():
        shutil.rmtree(target)
    with tarfile.open(archive_path) as tar:
        tar.extractall(CACHE_DIR, filter="data")
    marker.write_text(VERSION)
    print(f"utPLSQL {VERSION} extraído em {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
