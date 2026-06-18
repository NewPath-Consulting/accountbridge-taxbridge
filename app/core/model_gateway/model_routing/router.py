from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.core.model_gateway.model_routing.router_config import Candidate, Group, RouterConfig, load_router_config_from_env


@dataclass(frozen=True)
class RouteAttempt:
    provider: str
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    timeout_s: Optional[float] = None
    group: Optional[str] = None
    alias: Optional[str] = None


def _stable_bucket(*, key: str) -> int:
    # deterministic across processes
    h = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % 10_000


def _weighted_pick(candidates: Sequence[Candidate], *, seed: str) -> int:
    weights = [max(0, int(c.weight)) for c in candidates]
    total = sum(weights)
    if total <= 0:
        return 0
    bucket = _stable_bucket(key=seed) % total
    running = 0
    for i, w in enumerate(weights):
        running += w
        if bucket < running:
            return i
    return 0


def _rotate_from(candidates: Sequence[Candidate], start_idx: int) -> List[Candidate]:
    if not candidates:
        return []
    start_idx = max(0, min(start_idx, len(candidates) - 1))
    return list(candidates[start_idx:]) + list(candidates[:start_idx])


def _team_from_user(user: Optional[str]) -> Optional[str]:
    """
    Minimal convention: allow `user="team:rest"` to drive team overrides.
    If there's no colon, treat `user` as team id directly.
    """

    if not user:
        return None
    u = str(user).strip()
    if not u:
        return None
    if ":" in u:
        return u.split(":", 1)[0]
    return u


def resolve_route_attempts(
    *,
    model: str,
    user: Optional[str],
    explicit_provider: Optional[str],
) -> Tuple[Optional[RouterConfig], Optional[Group], Optional[str], List[RouteAttempt]]:
    """
    Determine which provider+model attempts to try, in order.

    If routing is not configured (no env var), returns empty attempts list.
    If explicit_provider is set, routing is bypassed (caller asked for a provider).
    """

    cfg = load_router_config_from_env()
    if cfg is None:
        return None, None, None, []

    if explicit_provider:
        # When caller already chose a provider, don't override that decision.
        return cfg, None, None, []

    alias = None
    group_name = None

    # Per-team alias overrides
    team = _team_from_user(user)
    if team and team in cfg.teams:
        team_over = cfg.teams[team]
        if model in team_over.alias_overrides:
            group_name = team_over.alias_overrides[model].get("group")
            alias = model

    # Standard alias mapping
    if group_name is None and model in cfg.aliases:
        alias = model
        group_name = cfg.aliases[model].get("group")

    # Group direct addressing (model == group name)
    if group_name is None and model in cfg.groups:
        group_name = model

    if not group_name:
        # Not a routed alias/group → treat as a normal model
        return cfg, None, None, []

    group = cfg.groups.get(group_name)
    if group is None:
        return cfg, None, alias, []

    # weighted_hash selection + fallback order
    seed = f"{user or 'anonymous'}::{group.name}"
    primary_idx = _weighted_pick(group.candidates, seed=seed)
    ordered = _rotate_from(group.candidates, primary_idx)

    attempts: List[RouteAttempt] = []
    for c in ordered:
        api_key = os.getenv(c.api_key_env) if c.api_key_env else None
        attempts.append(
            RouteAttempt(
                provider=c.provider,
                model=c.model,
                api_base=c.api_base,
                api_key=api_key,
                timeout_s=c.timeout_s,
                group=group.name,
                alias=alias,
            )
        )

    return cfg, group, alias, attempts


class CircuitBreaker:
    """
    In-memory circuit breaker keyed by (provider, model, api_base).

    - After N failures, the circuit is opened for cooldown_seconds.
    - After cooldown, it allows attempts again (no special 'half-open' state needed for v1).
    """

    def __init__(self, *, open_after_failures: int, cooldown_seconds: int):
        self._open_after_failures = max(1, int(open_after_failures))
        self._cooldown_seconds = max(1, int(cooldown_seconds))
        self._failures: dict[Tuple[str, str, Optional[str]], int] = {}
        self._opened_at: dict[Tuple[str, str, Optional[str]], float] = {}

    def _key(self, attempt: RouteAttempt) -> Tuple[str, str, Optional[str]]:
        return (attempt.provider, attempt.model, attempt.api_base)

    def is_open(self, attempt: RouteAttempt) -> bool:
        k = self._key(attempt)
        opened = self._opened_at.get(k)
        if opened is None:
            return False
        if (time.time() - opened) >= self._cooldown_seconds:
            # cooldown passed → close circuit
            self._opened_at.pop(k, None)
            self._failures.pop(k, None)
            return False
        return True

    def record_success(self, attempt: RouteAttempt) -> None:
        k = self._key(attempt)
        self._failures.pop(k, None)
        self._opened_at.pop(k, None)

    def record_failure(self, attempt: RouteAttempt) -> None:
        k = self._key(attempt)
        self._failures[k] = self._failures.get(k, 0) + 1
        if self._failures[k] >= self._open_after_failures:
            self._opened_at[k] = time.time()


