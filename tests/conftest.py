"""Shared test bootstrap: refresh the platform, then run plugin discovery once,
exactly like init_app.

The refresh must happen before anything below imports a fap symbol. It stamps
the platform marker, so app.py's own ensure_fresh_platform() is a no-op when a
test imports it - otherwise a purge mid-collection would swap module identities
underneath tests that already hold references to them.
"""
from fap.core.version import ensure_fresh_platform

ensure_fresh_platform()

from fap.exports.base import load_builtin_exporters
from fap.metrics.base import load_builtin_metrics
from fap.providers.base import load_builtin_providers
from fap.visuals.base import load_builtin_visuals

load_builtin_providers()
load_builtin_metrics()
load_builtin_visuals()
load_builtin_exporters()
