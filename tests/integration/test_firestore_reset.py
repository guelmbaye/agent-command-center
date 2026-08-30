"""`FirestoreStore.reset()` is executed, not merely read.

The first implementation called `logger.info(...)` in a module that defines no
`logger`. Every test passed: they inspected the source as text and never ran a
single line of it. Deployed, the Reset control answered 500 on a NameError.

A fake Firestore client is enough to execute the real method — no emulator, no
credentials, no network.
"""
from __future__ import annotations

import pytest

from apps.api.repositories.firestore_store import FirestoreStore


class _FakeDoc:
    def __init__(self, store: dict, path: str) -> None:
        self._store, self.path = store, path
        self._subs: dict[str, _FakeCollection] = {}

    @property
    def reference(self):
        return self

    def collection(self, name: str) -> "_FakeCollection":
        return self._subs.setdefault(name, _FakeCollection(self._store,
                                                           f"{self.path}/{name}"))

    async def delete(self) -> None:
        self._store.pop(self.path, None)


class _FakeCollection:
    def __init__(self, store: dict, path: str) -> None:
        self._store, self.path = store, path

    def document(self, doc_id: str) -> _FakeDoc:
        return _FakeDoc(self._store, f"{self.path}/{doc_id}")

    def add(self, doc_id: str) -> _FakeDoc:
        doc = self.document(doc_id)
        self._store[doc.path] = True
        return doc

    async def stream(self):
        prefix = f"{self.path}/"
        for path in [p for p in list(self._store)
                     if p.startswith(prefix) and "/" not in p[len(prefix):]]:
            yield _FakeDoc(self._store, path)


class _FakeDb:
    def __init__(self) -> None:
        self.store: dict[str, bool] = {}

    def collection(self, name: str) -> _FakeCollection:
        return _FakeCollection(self.store, name)


def _store_with_data(demo_mode: bool) -> tuple[FirestoreStore, _FakeDb]:
    store = FirestoreStore.__new__(FirestoreStore)  # no real client
    db = _FakeDb()
    store.db = db
    store._demo_mode = demo_mode

    mission = db.collection("missions").add("MIS-1001")
    for name in FirestoreStore.MISSION_SUBCOLLECTIONS:
        mission.collection(name).add("X-1")
    db.collection("approvals_index").add("APR-1")
    db.collection("security_events").add("SEC-1")
    db.collection("idempotency").add("KEY-1")
    return store, db


async def test_reset_actually_runs_and_empties_everything():
    store, db = _store_with_data(demo_mode=True)
    assert db.store, "the fixture must start with data"

    await store.reset()

    assert db.store == {}, f"documents survived: {sorted(db.store)}"


async def test_reset_removes_every_subcollection():
    """Firestore has no recursive delete: an orphan is invisible to every query."""
    store, db = _store_with_data(demo_mode=True)
    before = {p for p in db.store if p.startswith("missions/MIS-1001/")}
    assert len(before) == len(FirestoreStore.MISSION_SUBCOLLECTIONS)

    await store.reset()

    assert not [p for p in db.store if p.startswith("missions/")]


async def test_reset_is_refused_outside_demo_mode():
    store, db = _store_with_data(demo_mode=False)
    with pytest.raises(NotImplementedError):
        await store.reset()
    assert db.store, "nothing may be deleted when demo mode is off"
