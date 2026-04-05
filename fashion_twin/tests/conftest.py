"""Pytest fixtures."""

import os
import pytest

# Override env so tests never touch real DBs
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/fashion_twin_test")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "fashion_items_test")

from config import get_settings
get_settings.cache_clear()
