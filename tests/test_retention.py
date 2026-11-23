"""Keep the last complete sample across a real callback disconnect/reconnect."""

import asyncio
from unittest.mock import AsyncMock

from custom_components.manyi_local import hub as hub_module
from custom_components.manyi_local.hub import ManyiHub


def test_disconnect_and_failed_reconnect_preserve_measurements(monkeypatch):
    async def run():
        hub = ManyiHub({
            'advertised_ip': '127.0.0.1', 'tcp_port': 0, 'udp_port': 58899,
            'poll_seconds': 3600, 'inverters': [{
                'ip': '127.0.0.1', 'pn': 'I12345678901234', 'name': 'Test',
                'wire_mode': 'framed', 'slave_id': 4,
            }],
        })
        ip = '127.0.0.1'
        monkeypatch.setattr(hub_module, 'request_callback', AsyncMock(return_value=True))
        monkeypatch.setattr(hub_module.CollectorSession, 'identify', AsyncMock(return_value='I12345678901234'))
        monkeypatch.setattr(hub, '_read_settings', AsyncMock())
        monkeypatch.setattr(hub, '_read_values', AsyncMock(return_value={'inverter_battery_voltage': 52.3}))
        hub.settings_raw[ip][20148] = 80
        updated = asyncio.Event()
        hub.async_add_listener(ip, updated.set)
        await hub.async_start()
        port = hub._server.sockets[0].getsockname()[1]

        async def wait_until(predicate):
            async with asyncio.timeout(1):
                while not predicate():
                    updated.clear()
                    await updated.wait()

        try:
            _, writer = await asyncio.open_connection(ip, port)
            await wait_until(lambda: hub.states[ip]['values'].get('inverter_battery_voltage') == 52.3)
            timestamp = hub.value_updated[ip]['inverter_battery_voltage']
            writer.close()
            await writer.wait_closed()
            await wait_until(lambda: not hub.states[ip]['connected'])
            assert hub.states[ip]['values']['inverter_battery_voltage'] == 52.3
            assert hub.states[ip]['values']['setting_20148'] == 80
            monkeypatch.setattr(hub, '_read_values', AsyncMock(side_effect=TimeoutError))
            disconnected = asyncio.Event()
            hub.async_add_listener(ip, lambda: disconnected.set() if not hub.states[ip]['connected'] else None)
            _, writer = await asyncio.open_connection(ip, port)
            await asyncio.wait_for(disconnected.wait(), 1)
            writer.close()
            await writer.wait_closed()
            assert hub.states[ip]['values']['inverter_battery_voltage'] == 52.3
            assert hub.value_updated[ip]['inverter_battery_voltage'] == timestamp
            assert hub.settings_raw[ip][20148] == 80
            assert not hub._sessions
            # Explicit BMS absence must still invalidate the current BMS data.
            hub._publish_values(ip, {'bms_soh': 99})
            hub._publish_values(ip, {'bms_soh': None})
            assert hub.states[ip]['values']['bms_soh'] is None
        finally:
            await hub.async_stop()

    asyncio.run(run())
