"""Shared core utilities for Tarka services."""

from tarka_core.ast_definition import CustomSignalAstDict
from tarka_core.cache import KeyValueCache, LocalDictCache, RedisCache
from tarka_core.data_residency import (
    DataResidencyViolationError,
    assert_vendor_residency_allowed,
    coerce_residency,
)
from tarka_core.database import (
    build_async_database_url,
    create_audit_async_engine,
    install_sqlite_migration_compilers,
    resolve_tarka_db_engine,
    sync_url_for_alembic,
)
from tarka_core.engine_adapter import (
    SignalResolver,
    default_signal_resolver,
    merge_features_with_resolved_from_ast,
    merge_features_with_resolved_from_packs,
    register_custom_signal,
    unregister_custom_signal,
)
from tarka_core.infra import is_tarka_micro_environ
from tarka_core.internal_monitor import InternalMonitor
from tarka_core.messaging import (
    DeadLetterMessage,
    EphemeralDiskBufferBroker,
    LocalAsyncBroker,
    MessageBroker,
    NatsBroker,
    PublishDelivery,
    default_message_buffer_db_path,
    replay_disk_buffer_to_broker,
)
from tarka_core.templates import (
    INDUSTRY_RULE_TEMPLATE_ASTS,
    INDUSTRY_TEMPLATE_KEYS,
    list_industry_template_items,
)
from tarka_core.tenant_config import DataResidencyRegion, TenantConfig, tenant_config_from_mapping

__all__ = [
    "CustomSignalAstDict",
    "SignalResolver",
    "default_signal_resolver",
    "merge_features_with_resolved_from_ast",
    "merge_features_with_resolved_from_packs",
    "register_custom_signal",
    "unregister_custom_signal",
    "DataResidencyRegion",
    "DataResidencyViolationError",
    "DeadLetterMessage",
    "EphemeralDiskBufferBroker",
    "TenantConfig",
    "KeyValueCache",
    "LocalAsyncBroker",
    "LocalDictCache",
    "MessageBroker",
    "NatsBroker",
    "PublishDelivery",
    "default_message_buffer_db_path",
    "replay_disk_buffer_to_broker",
    "RedisCache",
    "assert_vendor_residency_allowed",
    "coerce_residency",
    "build_async_database_url",
    "create_audit_async_engine",
    "install_sqlite_migration_compilers",
    "InternalMonitor",
    "is_tarka_micro_environ",
    "resolve_tarka_db_engine",
    "sync_url_for_alembic",
    "tenant_config_from_mapping",
    "INDUSTRY_RULE_TEMPLATE_ASTS",
    "INDUSTRY_TEMPLATE_KEYS",
    "list_industry_template_items",
]
