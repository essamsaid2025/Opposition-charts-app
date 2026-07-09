import pytest

from fap.core.exceptions import PluginError, PluginNotFoundError
from fap.core.plugin import Plugin, PluginInfo, PluginRegistry


class Dummy(Plugin):
    info = PluginInfo(id="dummy", name="Dummy")


def test_register_and_get() -> None:
    reg: PluginRegistry[Dummy] = PluginRegistry("test")
    reg.register(Dummy)
    assert reg.get("dummy") is Dummy
    assert "dummy" in reg and len(reg) == 1


def test_duplicate_id_rejected() -> None:
    reg: PluginRegistry[Dummy] = PluginRegistry("test")
    reg.register(Dummy)

    class Clash(Plugin):
        info = PluginInfo(id="dummy", name="Clash")

    with pytest.raises(PluginError):
        reg.register(Clash)


def test_missing_plugin() -> None:
    reg: PluginRegistry[Dummy] = PluginRegistry("test")
    with pytest.raises(PluginNotFoundError):
        reg.get("nope")
