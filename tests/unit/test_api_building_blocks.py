"""Peças das APIs: limite de requisições, cursor e assinatura HMAC."""

from __future__ import annotations

import pytest

from source_systems.common.pagination import (
    Cursor,
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
)
from source_systems.common.rate_limit import TokenBucketLimiter
from source_systems.common.webhooks import sign, signature_header, verify_signature
from tests.conftest import FakeClock


def test_rate_limiter_allows_burst_then_asks_to_wait() -> None:
    clock = FakeClock()
    limiter = TokenBucketLimiter(per_minute=60, burst=3, clock=clock.monotonic)
    assert [limiter.acquire("cliente") for _ in range(3)] == [0.0, 0.0, 0.0]
    wait = limiter.acquire("cliente")
    assert wait == pytest.approx(1.0)  # 60/min = uma ficha por segundo
    clock.advance(1.0)
    assert limiter.acquire("cliente") == 0.0


def test_rate_limiter_is_per_client() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1, clock=FakeClock().monotonic)
    assert limiter.acquire("a") == 0.0
    assert limiter.acquire("a") > 0
    assert limiter.acquire("b") == 0.0


def test_cursor_round_trip_and_garbage() -> None:
    cursor = Cursor("2026-10-01T10:00:00.000000Z", "B2B-20261001-00001")
    assert decode_cursor(encode_cursor(cursor)) == cursor
    with pytest.raises(InvalidCursorError):
        decode_cursor("isto-nao-e-um-cursor")


def test_signature_verification() -> None:
    body = b'{"event_id":"1"}'
    header = signature_header("segredo", 1_700_000_000, body)
    assert header == f"t=1700000000,v1={sign('segredo', 1_700_000_000, body)}"
    assert verify_signature("segredo", header, body, now=1_700_000_010)
    assert not verify_signature("outro", header, body, now=1_700_000_010)
    assert not verify_signature("segredo", header, body + b" ", now=1_700_000_010)
    # Assinatura velha (replay) é recusada mesmo sendo válida.
    assert not verify_signature("segredo", header, body, now=1_700_000_000 + 3600)
    assert not verify_signature("segredo", "lixo", body, now=1_700_000_000)
