"""Geradores aleatórios derivados da seed global e de chaves (fluxo, data)."""

from __future__ import annotations

import hashlib
import random
import uuid


def rng_for(seed: int, *keys: object) -> random.Random:
    material = ":".join([str(seed), *(str(k) for k in keys)]).encode()
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def uuid_from(rng: random.Random) -> uuid.UUID:
    """UUID v4 reprodutível a partir do gerador."""
    return uuid.UUID(int=rng.getrandbits(128), version=4)
