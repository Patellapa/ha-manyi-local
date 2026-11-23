"""Configuration reads must tolerate unsupported firmware registers."""

import asyncio
import json
from pathlib import Path

from custom_components.manyi_local.settings import SETTINGS, SETTING_ADDRESSES
from custom_components.manyi_local.protocol import ModbusException
from test_telemetry import make_hub


def test_catalog_and_translations():
    assert len(SETTING_ADDRESSES) == 28
    assert len(SETTINGS) == 38
    assert len({item.key for item in SETTINGS}) == 38
    root = Path(__file__).parents[1] / 'custom_components/manyi_local'
    for filename in ('strings.json', 'translations/en.json', 'translations/it.json'):
        entities = json.loads((root / filename).read_text(encoding='utf-8'))['entity']['sensor']
        assert all(item.key in entities for item in SETTINGS)
    by_address = {item.address: item for item in SETTINGS if item.bit is None}
    assert by_address[10103].decode(540) == 54
    assert by_address[20103].decode(5000) == 50
    assert by_address[20148].decode(80) == 80
    assert by_address[20145].decode(1) == 'SOC'
    assert by_address[20145].decode(7) == 'unknown_7'
    flag = next(item for item in SETTINGS if item.bit == 8)
    assert flag.decode(256) == 'on'
    assert flag.decode(0) == 'off'


def test_optional_reads_are_bounded_cached_and_isolated():
    async def run():
        hub = make_hub()
        config = next(iter(hub.configs.values()))
        calls = []

        class Session:
            async def read_holding(self, address, count):
                calls.append((address, count))
                if address == 10101:
                    raise ModbusException(2)
                return [540]

        session = Session()
        await hub._read_settings(session, config)
        assert calls == [(address, 1) for address in SETTING_ADDRESSES[:4]]
        values = {'inverter_output_voltage': 230}
        hub._merge_settings(config.ip, values)
        assert values['setting_10101'] is None
        assert values['setting_10103'] == 54
        assert values['inverter_output_voltage'] == 230
        for _ in range(6):
            await hub._read_settings(session, config)
        assert len(calls) == 28
        await hub._read_settings(session, config)
        assert len(calls) == 28
        hub._settings_due[config.ip][10103] = 0
        await hub._read_settings(session, config)
        assert calls[-1] == (10103, 1)
        assert len(calls) == 29

    asyncio.run(run())


def test_timeout_does_not_retry_same_address_on_reconnection():
    async def run():
        hub = make_hub()
        config = next(iter(hub.configs.values()))
        calls = []

        class Session:
            async def read_holding(self, address, count):
                calls.append(address)
                raise TimeoutError

        await hub._read_settings(Session(), config)
        await hub._read_settings(Session(), config)
        assert calls == list(SETTING_ADDRESSES[:2])
        assert hub.settings_raw[config.ip][10101] is None

    asyncio.run(run())
