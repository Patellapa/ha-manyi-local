"""Config flow and startup regressions using the Home Assistant runtime."""
import asyncio
import errno
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

pytest.importorskip("homeassistant")
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady
from custom_components import manyi_local
from custom_components.manyi_local import config_flow
from custom_components.manyi_local.config_flow import ConfigFlow

SETTINGS = {"advertised_ip": "192.0.2.10", "tcp_port": 8899,
            "udp_port": 58899, "poll_seconds": 15}
LOGGER = {"name": "Inverter 1", "ip": "192.0.2.20", "pn": "I12345678901234",
          "wire_mode": "framed", "slave_id": 4}


def make_flow(monkeypatch):
    flow = ConfigFlow()
    flow.hass = SimpleNamespace(async_create_task=asyncio.create_task)
    for name in ("async_show_form", "async_show_menu", "async_show_progress", "async_show_progress_done"):
        monkeypatch.setattr(flow, name, lambda **kw: kw)
    return flow


def test_auto_scan_selection_and_names(monkeypatch):
    async def run():
        flow = make_flow(monkeypatch)
        monkeypatch.setattr(config_flow.network, "async_get_adapters", AsyncMock(return_value=[
            {"ipv4": [{"address": "192.0.2.10", "network_prefix": 24}]}
        ]))
        scanner = AsyncMock(return_value=[LOGGER])
        monkeypatch.setattr(config_flow, "discover", scanner)
        monkeypatch.setattr(config_flow, "check_port", AsyncMock())
        result = await flow.async_step_auto()
        assert result["step_id"] == "auto"
        assert result["data_schema"]({})["advertised_ip"] == "192.0.2.10"
        result = await flow.async_step_auto(SETTINGS)
        assert result["progress_action"] == "scanning_network"
        await flow._scan_task
        assert (await flow.async_step_scanning())["next_step_id"] == "scan_results"
        assert (await flow.async_step_scan_results({"devices": []}))["errors"]["base"] == "select_devices"
        result = await flow.async_step_scan_results({"devices": [LOGGER["pn"]]})
        assert result["step_id"] == "names"
        finish = AsyncMock(return_value={"saved": True})
        monkeypatch.setattr(flow, "_async_finish", finish)
        assert await flow.async_step_names({"name_0": " Roof "}) == {"saved": True}
        assert flow._inverters[0] == {**LOGGER, "name": "Roof"}
        scanner.assert_awaited_once_with("192.0.2.10", "192.0.2.0/24", 8899, 58899, deep=False)
    asyncio.run(run())


def test_scan_race_and_empty_results(monkeypatch):
    async def run():
        flow = make_flow(monkeypatch)
        flow._settings = dict(SETTINGS)
        flow._adapters = {"192.0.2.10": "192.0.2.0/24"}
        flow._deep = False
        monkeypatch.setattr(config_flow, "discover", AsyncMock(side_effect=OSError(errno.EADDRINUSE, "used")))
        await flow._async_scan()
        assert (await flow.async_step_scan_results())["errors"]["base"] == "port_in_use"
        flow._scan_error = None
        assert (await flow.async_step_scan_results())["step_id"] == "not_found"
    asyncio.run(run())


def test_manual_busy_port_retains_input(monkeypatch):
    async def run():
        flow = make_flow(monkeypatch)
        monkeypatch.setattr(config_flow, "check_port", AsyncMock(side_effect=OSError(errno.EADDRINUSE, "used")))
        data = {**SETTINGS, "inverter_count": 2, "tcp_port": 8901}
        result = await flow.async_step_manual(data)
        assert result["errors"] == {"base": "port_in_use"}
        assert result["data_schema"]({})["tcp_port"] == 8901
        assert flow._inverters == []
    asyncio.run(run())


def test_reconfigure_preserves_loggers_and_checks_changed_port(monkeypatch):
    async def run():
        flow = make_flow(monkeypatch)
        entry = SimpleNamespace(data={**SETTINGS, "inverters": [LOGGER]})
        monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
        update = Mock(return_value={"updated": True})
        monkeypatch.setattr(flow, "async_update_reload_and_abort", update)
        check = AsyncMock()
        monkeypatch.setattr(config_flow, "check_port", check)
        assert await flow.async_step_reconfigure(SETTINGS) == {"updated": True}
        check.assert_not_awaited()
        check.side_effect = OSError(errno.EADDRINUSE, "used")
        result = await flow.async_step_reconfigure({**SETTINGS, "tcp_port": 8900})
        assert result["errors"]["base"] == "port_in_use"
        assert update.call_count == 1
        assert entry.data["inverters"] == [LOGGER]
    asyncio.run(run())


def test_startup_busy_port_is_actionable_and_retries(monkeypatch):
    async def run():
        hub = SimpleNamespace(async_start=AsyncMock(side_effect=OSError(errno.EADDRINUSE, "used")),
                              async_stop=AsyncMock())
        monkeypatch.setattr(manyi_local, "ManyiHub", lambda data: hub)
        notify = Mock()
        monkeypatch.setattr(persistent_notification, "async_create", notify)
        hass = SimpleNamespace(data={})
        entry = SimpleNamespace(entry_id="test", data=dict(SETTINGS))
        with pytest.raises(ConfigEntryNotReady) as caught:
            await manyi_local.async_setup_entry(hass, entry)
        assert caught.value.translation_key == "port_in_use"
        assert caught.value.translation_placeholders == {"port": "8899"}
        hub.async_stop.assert_awaited_once()
        notify.assert_called_once()
        assert "Riconfigura" in notify.call_args.args[1]
        assert hass.data == {}
    asyncio.run(run())
