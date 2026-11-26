"""Autenticação, limite de requisições e injeção de caos nas rotas /v1."""

from __future__ import annotations

import hmac
import math
import random
import threading
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Header, HTTPException, status

from simulator.chaos import ApiChaos, ChaosLedger
from source_systems.common.rate_limit import TokenBucketLimiter
from source_systems.common.settings import ApiSettings


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _same_secret(given: str | None, expected: str) -> bool:
    # comparação em tempo constante
    return given is not None and bool(expected) and hmac.compare_digest(given, expected)


class ApiGuard:
    def __init__(
        self,
        settings: ApiSettings,
        chaos: ApiChaos,
        ledger: ChaosLedger,
        chaos_seed: int = 0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.chaos = chaos
        self.ledger = ledger
        self.limiter = TokenBucketLimiter(
            settings.rate_limit_per_minute, settings.rate_limit_burst, monotonic
        )
        self._rng = random.Random(chaos_seed)
        self._rng_lock = threading.Lock()
        self._sleep = sleep

    def _inject_chaos(self) -> None:
        with self._rng_lock:
            outage = self.chaos.outage.fires(self._rng)
            delay_ms = 0
            if not outage and self.chaos.latency.fires(self._rng):
                delay_ms = self._rng.randint(
                    self.chaos.latency.min_ms,
                    max(self.chaos.latency.min_ms, self.chaos.latency.max_ms),
                )
        if outage:
            self.ledger.record("outage", status_code=503)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Serviço temporariamente indisponível",
                headers={"Retry-After": "5"},
            )
        if delay_ms:
            self.ledger.record("latency", delay_ms=delay_ms)
            self._sleep(delay_ms / 1000)

    def client(self, authorization: Annotated[str | None, Header()] = None) -> str:
        """Dependência das rotas /v1: devolve o token do cliente autenticado."""
        self._inject_chaos()
        token = _bearer_token(authorization)
        if token is None or not _same_secret(token, self.settings.api_token.get_secret_value()):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Token ausente ou inválido",
                headers={"WWW-Authenticate": "Bearer"},
            )
        wait_seconds = self.limiter.acquire(token)
        if wait_seconds > 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Limite de requisições excedido",
                headers={"Retry-After": str(math.ceil(wait_seconds))},
            )
        return token

    def admin(self, authorization: Annotated[str | None, Header()] = None) -> None:
        """Dependência das rotas /admin (só o simulador usa)."""
        if not _same_secret(
            _bearer_token(authorization), self.settings.admin_token.get_secret_value()
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Token de administração inválido",
                headers={"WWW-Authenticate": "Bearer"},
            )
