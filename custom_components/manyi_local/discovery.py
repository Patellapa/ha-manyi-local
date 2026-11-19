"""Bounded LAN discovery; every candidate is identified over TCP before display."""
import asyncio
import ipaddress
import logging
import socket

from .hub import CollectorConfig
from .protocol import ProtocolError
from .transport import CollectorSession

_LOGGER = logging.getLogger(__name__)


async def check_port(port):
    """Check the actual listener address and release it immediately."""
    server = await asyncio.start_server(lambda r, w: w.close(), "0.0.0.0", port)
    server.close()
    await server.wait_closed()


async def discover(advertised_ip, network_cidr, tcp_port, udp_port, *, deep=False,
                   duration=10):
    network = ipaddress.IPv4Network(network_cidr, strict=False)
    tasks = set()
    active = set()
    results = {}
    stopping = False
    semaphore = asyncio.Semaphore(8)

    async def accept(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        session = None
        ip = writer.get_extra_info("peername")[0]
        admitted = False
        try:
            if stopping or ipaddress.IPv4Address(ip) not in network or ip in active or len(active) >= 8:
                return
            active.add(ip)
            admitted = True
            async with semaphore:
                config = CollectorConfig(name=ip, ip=ip, pn="", wire_mode="framed", slave_id=4)
                session = CollectorSession(reader, writer, config, 3)
                async with asyncio.timeout(7):
                    pn = await session.read_identity()
                if len(results) >= 32 and pn not in results:
                    return
                results[pn] = {"ip": ip, "pn": pn, "name": f"Inverter {len(results) + 1}",
                               "wire_mode": "framed", "slave_id": 4}
        except (OSError, EOFError, asyncio.LimitOverrunError, ProtocolError, UnicodeError, ValueError) as exc:
            _LOGGER.debug("Discovery identity failed for %s: %s", ip, exc)
        finally:
            if session is not None:
                await session.close()
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            if admitted:
                active.discard(ip)
            tasks.discard(task)

    server = await asyncio.start_server(accept, "0.0.0.0", tcp_port)
    try:
        tcp_port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        message = f"set>server={advertised_ip}:{tcp_port};".encode("ascii")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((advertised_ip, 0))
            targets = [str(network.broadcast_address)]
            if deep:
                if network.num_addresses > 1024:
                    raise ValueError("network_too_large")
                targets += [str(ip) for ip in network.hosts() if str(ip) != advertised_ip]
            for attempt in range(2):
                for index, target in enumerate(targets):
                    await loop.sock_sendto(sock, message, (target, udp_port))
                    if index % 16 == 0:
                        await asyncio.sleep(0.02)
                await asyncio.sleep(duration / 2)
    finally:
        stopping = True
        server.close()
        await server.wait_closed()
        for task in tuple(tasks):
            task.cancel()
        await asyncio.gather(*tuple(tasks), return_exceptions=True)
    return sorted(results.values(), key=lambda item: (item["ip"], item["pn"]))
