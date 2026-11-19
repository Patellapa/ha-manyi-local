"""Regression checks that require a Home Assistant runtime."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorEntityDescription

from custom_components import manyi_local
from custom_components.manyi_local.const import DOMAIN
from custom_components.manyi_local.sensor import (
    BATTERY_SENSORS,
    INVERTER_SENSORS,
    MPPT_SENSORS,
    ManyiSensor,
    async_setup_entry,
)


def test_sensor_platform_creates_entities_with_sensor_units():
    async def run():
        config = SimpleNamespace(
            name="Test", pn="I12345678901234", ip="192.0.2.20"
        )
        entry = SimpleNamespace(
            entry_id="test",
            data={
                "inverters": [{
                    "name": config.name,
                    "pn": config.pn,
                    "ip": config.ip,
                    "wire_mode": "framed",
                    "slave_id": 4,
                }]
            },
        )
        hub = SimpleNamespace(states={
            config.ip: {
                "connected": True,
                "values": {"inverter_output_voltage": 230},
            }
        })
        hass = SimpleNamespace(data={DOMAIN: {entry.entry_id: hub}})
        entities = []
        await async_setup_entry(hass, entry, entities.extend)

        assert len(entities) == 23
        assert len({entity.unique_id for entity in entities}) == 23
        voltage = entities[0]
        assert isinstance(voltage, ManyiSensor)
        assert voltage.native_unit_of_measurement == "V"
        assert voltage.native_value == 230
        for description in (*INVERTER_SENSORS, *MPPT_SENSORS, *BATTERY_SENSORS):
            assert isinstance(description, SensorEntityDescription)

    asyncio.run(run())


def test_failed_platform_setup_stops_listener_and_clears_entry(monkeypatch):
    from homeassistant.components import persistent_notification
    monkeypatch.setattr(persistent_notification, "async_dismiss", lambda *args: None)
    async def run():
        hub = SimpleNamespace(async_start=AsyncMock(), async_stop=AsyncMock())
        monkeypatch.setattr(manyi_local, "ManyiHub", lambda data: hub)
        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(
                    side_effect=ImportError("sensor platform failed")
                )
            ),
        )
        entry = SimpleNamespace(entry_id="test", data={})

        with pytest.raises(ImportError, match="sensor platform failed"):
            await manyi_local.async_setup_entry(hass, entry)

        hub.async_stop.assert_awaited_once()
        assert DOMAIN not in hass.data

    asyncio.run(run())
