"""Persistence backend selection."""
from __future__ import annotations

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.repositories.base import Store
from apps.api.repositories.memory_store import InMemoryStore

logger = get_logger("acc.store")

_store: Store | None = None


def get_store(settings: Settings | None = None) -> Store:
    """Process singleton (Settings is not hashable, so no lru_cache)."""
    global _store
    if _store is not None:
        return _store
    settings = settings or get_settings()
    if settings.acc_persistence == "firestore":
        try:
            from apps.api.repositories.firestore_store import FirestoreStore
            _store = FirestoreStore(settings.google_cloud_project,
                                    settings.firestore_database,
                                    demo_mode=settings.acc_demo_mode)
            logger.info("store_selected", extra={"backend": "firestore"})
            return _store
        except Exception as exc:  # pragma: no cover - degrade proprement
            logger.error("firestore_unavailable_fallback_memory", extra={"detail": str(exc)})
    _store = InMemoryStore()
    logger.info("store_selected", extra={"backend": "memory"})
    return _store


def reset_store() -> None:
    """Used by tests to start from a fresh store."""
    global _store
    _store = None
