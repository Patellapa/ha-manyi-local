"""Regression checks that require a Home Assistant runtime."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorEntityDescription

from custom_components import manyi_local
from custom_components.manyi_local.const import DOMAIN
from custom_components.manyi_local.binary_sensor import ManyiConnectionSensor
from test_telemetry import make_hub
from custom_components.manyi_local.sensor import (
    BATTERY_SENSORS,
    INVERTER_SENSORS,
    MPPT_SENSORS,
    SETTING_SENSORS,
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

        assert len(entities) == 23 + len(SETTING_SENSORS)
        assert len({entity.unique_id for entity in entities}) == len(entities)
        voltage = entities[0]
        assert isinstance(voltage, ManyiSensor)
        assert voltage.native_unit_of_measurement == "V"
        assert voltage.native_value == 230
        for description in (*INVERTER_SENSORS, *MPPT_SENSORS, *BATTERY_SENSORS, *SETTING_SENSORS):
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


def test_retained_sensor_state_has_explicit_freshness_and_connectivity():
    hub = make_hub()
    config = next(iter(hub.configs.values()))
    ip = config.ip
    voltage = ManyiSensor(hub, config, INVERTER_SENSORS[0])
    connection = ManyiConnectionSensor(hub, config)
    assert not voltage.available
    assert not connection.is_on
    hub.states[ip]['connected'] = True
    hub._publish_values(ip, {'inverter_output_voltage': 230})
    timestamp = hub.value_updated[ip]['inverter_output_voltage']
    assert voltage.available
    assert voltage.extra_state_attributes['register'] == 25206
    assert not voltage.extra_state_attributes['data_stale']
    assert connection.is_on
    hub.states[ip]['connected'] = False
    assert voltage.available
    assert voltage.native_value == 230
    assert voltage.extra_state_attributes['data_stale']
    assert voltage.extra_state_attributes['last_successful_update'] == timestamp
    assert not connection.is_on
    hub.states[ip]['connected'] = True
    hub.states[ip]['session_started'] = '9999-01-01T00:00:00+00:00'
    assert voltage.extra_state_attributes['data_stale']
    hub.states[ip]['session_started'] = timestamp
    hub._publish_values(ip, {'inverter_output_voltage': 231})
    assert voltage.native_value == 231
    assert not voltage.extra_state_attributes['data_stale']


def test_cached_settings_keep_raw_evidence_on_read_failure():
    hub = make_hub()
    config = next(iter(hub.configs.values()))
    ip = config.ip
    description = next(item for item in SETTING_SENSORS if item.key == 'setting_20149')
    sensor = ManyiSensor(hub, config, description)
    assert not sensor.available
    hub.settings_raw[ip][20149] = 8
    hub.value_updated[ip]['setting_20149'] = '2026-11-23T12:00:00+00:00'
    hub._merge_settings(ip, hub.states[ip]['values'])
    hub.states[ip]['connected'] = True
    assert sensor.native_value == '8'
    assert not sensor.extra_state_attributes['data_stale']
    hub.settings_errors[ip][20149] = 'TimeoutError'
    assert sensor.available
    assert sensor.extra_state_attributes['raw_value'] == 8
    assert sensor.extra_state_attributes['data_stale']
    assert sensor.extra_state_attributes['last_read_error'] == 'TimeoutError'
    hub._publish_values(ip, {'bms_soh': 99})
    description = next(item for item in BATTERY_SENSORS if item.key == 'bms_soh')
    soh = ManyiSensor(hub, config, description)
    assert soh.available
    hub._publish_values(ip, {'bms_soh': None})
    assert not soh.available
