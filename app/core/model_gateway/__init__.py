"""
AI Matic Model Gateway (lightweight).

Public surface intentionally small:
- completion APIs live in `model_gateway.aim_main`
- lightweight helpers (token_counter, embedding, custom providers) live here
"""

from __future__ import annotations

from .core import embedding, register_custom_provider, token_counter  # noqa: F401

__all__ = ["register_custom_provider", "token_counter", "embedding"]

