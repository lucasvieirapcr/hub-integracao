"""Documentos brasileiros sintéticos (CNPJ com dígitos verificadores válidos)."""

from __future__ import annotations

import random

_CNPJ_WEIGHTS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_WEIGHTS_2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def _check_digit(digits: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def generate_cnpj(rng: random.Random) -> str:
    """CNPJ matriz (0001) com dígitos verificadores corretos, só números."""
    base = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    first = _check_digit(base, _CNPJ_WEIGHTS_1)
    second = _check_digit([*base, first], _CNPJ_WEIGHTS_2)
    return "".join(str(d) for d in [*base, first, second])


def is_valid_cnpj(cnpj: str) -> bool:
    if len(cnpj) != 14 or not cnpj.isdigit() or len(set(cnpj)) == 1:
        return False
    digits = [int(c) for c in cnpj]
    return digits[12] == _check_digit(digits[:12], _CNPJ_WEIGHTS_1) and digits[13] == _check_digit(
        digits[:13], _CNPJ_WEIGHTS_2
    )
