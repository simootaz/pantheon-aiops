"""Shared fixtures.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def _settings_cache_is_not_shared_between_tests() -> Iterator[None]:
    """Clear the cached settings around every test.

    `get_settings()` is deliberately `lru_cache`d, so one test that sets an
    environment variable would otherwise leak its configuration into every test
    that ran after it - and, worse, the leak depends on execution order.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
