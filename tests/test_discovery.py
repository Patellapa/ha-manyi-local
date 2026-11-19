"""Exercise discovery using local TCP loggers and UDP requests, without real devices."""
import asyncio
import errno

import pytest

from custom_components.manyi_local.discovery import check_port, discover
from custom_components.manyi_local.protocol import frame, read_frame

PN = "I12345678901234"


def test_occupied_port_and_release():
    async def run():
        server = await asyncio.start_server(lambda r, w: w.close(), "0.0.0.0", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with pytest.raises(OSError) as caught:
                await check_port(port)
            assert caught.value.errno in (errno.EADDRINUSE, 10048)
        finally:
            server.close()
            await server.wait_closed()
        await check_port(port)
    asyncio.run(run())


@pytest.mark.parametrize("identity,expected", [(PN, True), ("invalid", False)])
def test_scan_verifies_identity_and_closes_listener(monkeypatch, identity, expected):
    async def run():
        loop = asyncio.get_running_loop()
        original = loop.sock_sendto
        connections = []
        ports = []

        async def logger(port):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                tid, _, _, fc, _ = await read_frame(reader)
                assert fc == 1
                writer.write(frame(tid, 1, b"", 0, 1))
                await writer.drain()
                tid, code, address, fc, payload = await read_frame(reader)
                assert (fc, payload) == (2, b"\x02")
                writer.write(frame(tid, 2, b"\x00\x02" + identity.encode(), code, address))
                await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()

        async def send(sock, data, target):
            assert target == ("127.255.255.255", 58899)
            port = int(data.decode().split(":")[-1].rstrip(";"))
            ports.append(port)
            connections.append(asyncio.create_task(logger(port)))
            return len(data)

        monkeypatch.setattr(loop, "sock_sendto", send)
        results = await discover("127.0.0.1", "127.0.0.0/8", 0, 58899, duration=0.15)
        # Port zero is useful in tests: discovery must advertise the actual bound port.
        await asyncio.gather(*connections)
        assert len(results) == int(expected)
        if expected:
            assert results[0]["pn"] == PN
            assert results[0]["ip"] == "127.0.0.1"
        await check_port(ports[0])
        monkeypatch.setattr(loop, "sock_sendto", original)
    asyncio.run(run())


def test_cancelled_scan_releases_port(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        ports = []
        async def send(sock, data, target):
            ports.append(int(data.decode().split(":")[-1].rstrip(";")))
            started.set()
            return len(data)
        monkeypatch.setattr(loop, "sock_sendto", send)
        task = asyncio.create_task(discover("127.0.0.1", "127.0.0.0/8", 0, 58899))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await check_port(ports[0])
    asyncio.run(run())
