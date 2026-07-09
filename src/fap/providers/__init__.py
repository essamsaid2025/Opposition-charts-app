"""Data provider plugins. Each provider turns an external source (file,
vendor API, database export) into a RAW DataFrame + column mapping. The
pipeline layer then normalizes everything into the canonical event schema."""
from fap.providers.base import DataProvider, provider_registry, load_builtin_providers
__all__ = ["DataProvider", "provider_registry", "load_builtin_providers"]
