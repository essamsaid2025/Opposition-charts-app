"""Shared test bootstrap: run plugin discovery once, exactly like init_app."""
from fap.exports.base import load_builtin_exporters
from fap.metrics.base import load_builtin_metrics
from fap.providers.base import load_builtin_providers
from fap.visuals.base import load_builtin_visuals

load_builtin_providers()
load_builtin_metrics()
load_builtin_visuals()
load_builtin_exporters()
