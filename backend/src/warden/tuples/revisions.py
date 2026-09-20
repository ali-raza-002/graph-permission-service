from __future__ import annotations

import time

from warden.core.consistency import Consistency, ConsistencyMode, decode_token
from warden.core.errors import InvalidConsistencyTokenError, NotFoundError, SnapshotTooOldError
from warden.model.repository import StoreRepository


class RevisionResolver:
    """Chooses the snapshot revision a read is evaluated at.

    minimize_latency reuses a recently observed revision for up to the quantization
    window, so concurrent checks land on the same revision and share cache entries.
    at_least_as_fresh accepts that cached revision only if it already covers the
    caller's token; otherwise it reads the current revision from the database.
    """

    def __init__(self, stores: StoreRepository, *, quantization_ms: int) -> None:
        self._stores = stores
        self._window = quantization_ms / 1000
        self._seen: dict[str, tuple[int, float]] = {}

    def observe(self, store_id: str, revision: int) -> None:
        previous = self._seen.get(store_id)
        if previous is None or revision >= previous[0]:
            self._seen[store_id] = (revision, time.monotonic())

    async def current(self, store_id: str) -> int:
        revision = await self._stores.revision(store_id)
        if revision is None:
            raise NotFoundError(f"store '{store_id}' does not exist")
        self.observe(store_id, revision)
        return revision

    def forget(self, store_id: str) -> None:
        self._seen.pop(store_id, None)

    async def exact(self, store_id: str, revision: int) -> int:
        """Validate that `revision` can be read: reached, and not yet garbage-collected."""
        bounds = await self._stores.revision_bounds(store_id)
        if bounds is None:
            raise NotFoundError(f"store '{store_id}' does not exist")
        current, horizon = bounds
        self.observe(store_id, current)
        if revision > current:
            raise InvalidConsistencyTokenError(
                "consistency token refers to a revision this store has not reached"
            )
        if revision < horizon:
            raise SnapshotTooOldError(
                f"revision {revision} is older than the retained history (oldest readable "
                f"revision is {horizon}); retry with a fresh read"
            )
        return revision

    def _recent(self, store_id: str) -> int | None:
        seen = self._seen.get(store_id)
        if seen is None or time.monotonic() - seen[1] > self._window:
            return None
        return seen[0]

    async def resolve(self, store_id: str, consistency: Consistency | None) -> int:
        consistency = consistency or Consistency()
        match consistency.mode:
            case ConsistencyMode.FULLY_CONSISTENT:
                return await self.current(store_id)
            case ConsistencyMode.MINIMIZE_LATENCY:
                recent = self._recent(store_id)
                return recent if recent is not None else await self.current(store_id)
            case ConsistencyMode.AT_LEAST_AS_FRESH:
                wanted = decode_token(consistency.token or "", store_id)
                recent = self._recent(store_id)
                if recent is not None and recent >= wanted:
                    return recent
                current = await self.current(store_id)
                if current < wanted:
                    raise InvalidConsistencyTokenError(
                        "consistency token refers to a revision this store has not reached"
                    )
                return current
            case ConsistencyMode.AT_EXACT_SNAPSHOT:
                return await self.exact(store_id, decode_token(consistency.token or "", store_id))
