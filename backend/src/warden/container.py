from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from warden.auth.keys import ApiKeyService
from warden.cache.backends import CheckCache, MemoryCache, NullCache, RedisCache
from warden.config import Settings
from warden.db.database import Database
from warden.decisions.repository import DecisionRepository
from warden.decisions.service import DecisionLog, DecisionService
from warden.maintenance import GarbageCollector
from warden.model.repository import ModelRepository, StoreRepository
from warden.model.service import ModelService, StoreService
from warden.queries.service import QueryLimits, QueryService
from warden.tuples.repository import TupleRepository
from warden.tuples.revisions import RevisionResolver
from warden.tuples.service import TupleService


def build_cache(settings: Settings) -> CheckCache:
    match settings.cache_backend:
        case "redis":
            return RedisCache.from_url(settings.redis_url, ttl_seconds=settings.cache_ttl_seconds)
        case "memory":
            return MemoryCache(
                max_entries=settings.cache_max_entries, ttl_seconds=settings.cache_ttl_seconds
            )
        case "none":
            return NullCache()


@dataclass
class Container:
    settings: Settings
    db: Database
    cache: CheckCache
    stores: StoreService
    models: ModelService
    revisions: RevisionResolver
    tuples: TupleService
    queries: QueryService
    decision_log: DecisionLog
    decisions: DecisionService
    keys: ApiKeyService
    gc: GarbageCollector

    @classmethod
    def build(cls, settings: Settings) -> Container:
        db = Database(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            max_concurrent_reads=settings.max_concurrent_reads,
            echo=settings.db_echo,
        )
        cache = build_cache(settings)
        store_repo = StoreRepository(db)
        models = ModelService(store_repo, ModelRepository(db))
        revisions = RevisionResolver(store_repo, quantization_ms=settings.revision_quantization_ms)
        decision_repo = DecisionRepository(db)
        decision_log = DecisionLog(
            decision_repo,
            mode=settings.decision_log,
            flush_interval_ms=settings.decision_flush_interval_ms,
            max_trace_nodes=settings.decision_trace_max_nodes,
        )
        bootstrap = settings.bootstrap_admin_key
        return cls(
            settings=settings,
            db=db,
            cache=cache,
            stores=StoreService(store_repo, on_delete=[revisions.forget, models.forget_store]),
            models=models,
            revisions=revisions,
            tuples=TupleService(
                TupleRepository(db),
                models,
                revisions,
                max_tuples_per_write=settings.max_tuples_per_write,
            ),
            queries=QueryService(
                db,
                models,
                revisions,
                cache,
                decision_log,
                QueryLimits(
                    max_depth=settings.max_check_depth,
                    max_contextual_tuples=settings.max_contextual_tuples,
                    list_max_results=settings.list_max_results,
                    max_batch_checks=settings.max_batch_checks,
                    list_max_candidates=settings.list_max_candidates,
                    deadline_ms=settings.query_deadline_ms,
                ),
            ),
            decision_log=decision_log,
            decisions=DecisionService(decision_repo),
            keys=ApiKeyService(
                db,
                bootstrap_key=bootstrap.get_secret_value() if bootstrap else None,
                cache_ttl_seconds=settings.principal_cache_ttl_seconds,
                cache_max_entries=settings.principal_cache_max_entries,
            ),
            gc=GarbageCollector(
                db,
                decision_repo,
                history_retention=timedelta(hours=settings.tuple_history_retention_hours),
                decision_retention=timedelta(days=settings.decision_retention_days),
                interval_seconds=settings.gc_interval_seconds,
            ),
        )

    async def start(self) -> None:
        await self.decision_log.start()
        if self.settings.gc_enabled:
            await self.gc.start()

    async def close(self) -> None:
        await self.gc.stop()
        await self.decision_log.stop()
        await self.cache.close()
        await self.db.dispose()
