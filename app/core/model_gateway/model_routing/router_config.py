from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


ENV_CONFIG_JSON = "AIM_ROUTER_CONFIG_JSON"
ENV_CONFIG_PATH = "AIM_ROUTER_CONFIG_PATH"


RetryOn = Literal["timeout", "rate_limit", "http_5xx"]
Jitter = Literal["none", "full"]
Strategy = Literal["weighted_hash"]


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    weight: int = 100
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout_s: Optional[float] = None


@dataclass(frozen=True)
class Group:
    name: str
    strategy: Strategy
    candidates: List[Candidate]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    base_delay_ms: int = 200
    max_delay_ms: int = 2000
    jitter: Jitter = "full"
    retry_on: List[RetryOn] = None  # type: ignore[assignment]


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    open_after_failures: int = 5
    cooldown_seconds: int = 30


@dataclass(frozen=True)
class TeamOverride:
    alias_overrides: Dict[str, Dict[str, str]]


@dataclass(frozen=True)
class RouterConfig:
    version: int
    aliases: Dict[str, Dict[str, str]]
    groups: Dict[str, Group]
    retry: RetryPolicy
    circuit_breaker: CircuitBreakerPolicy
    teams: Dict[str, TeamOverride]


def _read_config_source() -> Optional[str]:
    raw = os.getenv(ENV_CONFIG_JSON)
    if raw and raw.strip():
        return raw
    path = os.getenv(ENV_CONFIG_PATH)
    if path and path.strip():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def load_router_config_from_env() -> Optional[RouterConfig]:
    """
    Returns None when routing is not configured.
    Raises ValueError when routing config is present but invalid.
    """

    raw = _read_config_source()
    if raw is None:
        return None

    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"Invalid JSON in {ENV_CONFIG_JSON}/{ENV_CONFIG_PATH}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Router config must be a JSON object")

    version = int(data.get("version", 1))
    aliases = data.get("aliases") or {}
    groups_raw = data.get("groups") or {}
    overrides = data.get("overrides") or {}
    teams_raw = (overrides.get("teams") or {}) if isinstance(overrides, dict) else {}

    retry_raw = data.get("retry") or {}
    cb_raw = data.get("circuit_breaker") or {}

    retry = RetryPolicy(
        max_attempts=int(retry_raw.get("max_attempts", 1)),
        base_delay_ms=int(retry_raw.get("base_delay_ms", 200)),
        max_delay_ms=int(retry_raw.get("max_delay_ms", 2000)),
        jitter=retry_raw.get("jitter", "full"),
        retry_on=list(retry_raw.get("retry_on", ["timeout", "rate_limit", "http_5xx"])),
    )

    circuit_breaker = CircuitBreakerPolicy(
        open_after_failures=int(cb_raw.get("open_after_failures", 5)),
        cooldown_seconds=int(cb_raw.get("cooldown_seconds", 30)),
    )

    groups: Dict[str, Group] = {}
    if not isinstance(groups_raw, dict):
        raise ValueError("groups must be a JSON object")
    for group_name, g in groups_raw.items():
        if not isinstance(g, dict):
            raise ValueError(f"group '{group_name}' must be an object")
        strategy = g.get("strategy", "weighted_hash")
        candidates_raw = g.get("candidates") or []
        if not isinstance(candidates_raw, list) or not candidates_raw:
            raise ValueError(f"group '{group_name}' must have non-empty candidates list")
        candidates: List[Candidate] = []
        for idx, c in enumerate(candidates_raw):
            if not isinstance(c, dict):
                raise ValueError(f"group '{group_name}' candidate[{idx}] must be an object")
            provider = c.get("provider")
            model = c.get("model")
            if not provider or not model:
                raise ValueError(f"group '{group_name}' candidate[{idx}] requires provider + model")
            candidates.append(
                Candidate(
                    provider=str(provider),
                    model=str(model),
                    weight=int(c.get("weight", 100)),
                    api_base=c.get("api_base"),
                    api_key_env=c.get("api_key_env"),
                    timeout_s=c.get("timeout_s"),
                )
            )
        groups[group_name] = Group(name=group_name, strategy=strategy, candidates=candidates)

    teams: Dict[str, TeamOverride] = {}
    if not isinstance(teams_raw, dict):
        raise ValueError("overrides.teams must be an object")
    for team_name, t in teams_raw.items():
        if not isinstance(t, dict):
            continue
        alias_overrides = t.get("alias_overrides") or {}
        if not isinstance(alias_overrides, dict):
            raise ValueError(f"team override '{team_name}'.alias_overrides must be an object")
        teams[str(team_name)] = TeamOverride(alias_overrides=alias_overrides)

    return RouterConfig(
        version=version,
        aliases=aliases,
        groups=groups,
        retry=retry,
        circuit_breaker=circuit_breaker,
        teams=teams,
    )


