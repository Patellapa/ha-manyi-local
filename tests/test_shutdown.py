"""Removal must finish even with connected, silent loggers (Python 3.14)."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.manyi_local.hub import ManyiHub
from custom_components.manyi_local import hub as hub_module


@pytest.mark.parametrize("polling", [False, True])
def test_stop_closes_active_callback_before_waiting_for_server(monkeypatch, polling):
    async def run():
        data = {"advertised_ip": "127.0.0.1", "tcp_port": 0, "udp_port": 58899,
                "poll_seconds": 3600, "inverters": [{"ip": "127.0.0.1", "pn": "I12345678901234",
                "name": "Test", "wire_mode": "framed", "slave_id": 4}]}
        hub = ManyiHub(data)
        monkeypatch.setattr(hub_module, "request_callback", AsyncMock(return_value=True))
        polling_started = asyncio.Event()
        if polling:
            monkeypatch.setattr(hub_module.CollectorSession, "identify", AsyncMock(return_value="I12345678901234"))
            async def read_values(*args):
                polling_started.set()
                await asyncio.Event().wait()
            monkeypatch.setattr(hub, "_read_values", read_values)
        await hub.async_start()
        port = hub._server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        stop = None
        try:
            if polling:
                await asyncio.wait_for(polling_started.wait(), 1)
            else:
                await asyncio.wait_for(reader.readexactly(16), 1)
            stop = asyncio.create_task(hub.async_stop())
            done, _ = await asyncio.wait({stop}, timeout=0.5)
            assert stop in done, "Shutdown is blocked by a connected logger"
            await stop
            assert not hub._connection_tasks
            assert not hub._sessions
            assert not hub._callback_tasks
            assert not hub.states["127.0.0.1"]["connected"]
            assert await asyncio.wait_for(reader.read(), 1) == b""
            replacement = await asyncio.start_server(lambda r, w: w.close(), "0.0.0.0", port)
            replacement.close()
            await replacement.wait_closed()
            await hub.async_stop()  # Idempotent cleanup.
        finally:
            writer.close()
            await writer.wait_closed()
            if stop is not None:
                stop.cancel()
                await asyncio.gather(stop, return_exceptions=True)
            for task in tuple(hub._connection_tasks) + tuple(hub._callback_tasks):
                task.cancel()
            await asyncio.gather(*tuple(hub._connection_tasks), *tuple(hub._callback_tasks), return_exceptions=True)
    asyncio.run(run())
