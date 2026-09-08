"""Tax990 e-filing adapter."""

from app.adapters.tax990.client import Tax990Client
from app.adapters.tax990.exceptions import (
    Tax990AuthError,
    Tax990Error,
    Tax990ReturnExistsError,
    Tax990ValidationError,
)

__all__ = [
    "Tax990Client",
    "Tax990Error",
    "Tax990AuthError",
    "Tax990ValidationError",
    "Tax990ReturnExistsError",
]
