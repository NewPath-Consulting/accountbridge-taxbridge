"""Benchmark comparison of generated vs reference financial reports."""

from app.core.benchmark.schemas import (
    BenchmarkDocument,
    BenchmarkResult,
    YearBenchmarkResult,
)

__all__ = [
    "BenchmarkService",
    "BenchmarkDocument",
    "BenchmarkResult",
    "YearBenchmarkResult",
]


def __getattr__(name: str):
    if name == "BenchmarkService":
        from app.core.benchmark.service import BenchmarkService
        return BenchmarkService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
