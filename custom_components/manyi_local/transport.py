"""TCP collector session and UDP callback request."""

import asyncio
import logging
import re
import socket

from .protocol import ProtocolError, frame, heartbeat, read_frame, read_request, read_response

_LOGGER = logging.getLogger(__name__)


class CollectorSession:
    def __init__(self, reader, writer, config, timeout: float) -> None:
        self.reader = reader
        self.writer = writer
        self.config = config
        self.timeout = timeout
        self.pending = {}
        self.lock = asyncio.Lock()
        self.tid = 0
        self.closed = False
        self.raw_future = None
        self.at_future = None
        self.heartbeat_reply = None
        self.heartbeat_task = None
        self.reader_task = asyncio.create_task(self._reader())

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        for task in (self.reader_task, self.heartbeat_task):
            if task is not None and asyncio.current_task() != task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _send_heartbeat(self, wait_for_reply: bool = False) -> None:
        self.tid = self.tid % 65535 + 1
        tid = self.tid
        future = asyncio.get_running_loop().create_future() if wait_for_reply else None
        if future is not None:
            self.heartbeat_reply = (tid, future)
        try:
            _LOGGER.debug("%s TX heartbeat tid=%s", self.config.name, tid)
            self.writer.write(heartbeat(tid))
            await asyncio.wait_for(self.writer.drain(), self.timeout)
            if future is not None:
                try:
                    await asyncio.wait_for(future, self.timeout)
                except TimeoutError as exc:
                    raise TimeoutError("initial_heartbeat_reply_timeout") from exc
        except (TimeoutError, ConnectionError):
            await self.close()
            raise
        finally:
            if future is not None:
                self.heartbeat_reply = None
                if not future.done():
                    future.cancel()

    async def _heartbeat_loop(self) -> None:
        try:
            while not self.closed:
                await asyncio.sleep(60)
                if not self.closed:
                    await self._send_heartbeat()
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError, ConnectionError) as exc:
            _LOGGER.warning(
                "Heartbeat failed for %s (%s): %s",
                self.config.name, type(exc).__name__, exc,
            )
            await self.close()

    async def _reader(self) -> None:
        error: Exception = ConnectionError("collector_disconnected")
        try:
            while True:
                first = await self.reader.readexactly(1)
                async with asyncio.timeout(self.timeout):
                    if first == b"A":
                        line = first + await self.reader.readuntil(b"\n")
                        if self.at_future and not self.at_future.done() and line.startswith(b"AT+DTUPN"):
                            self.at_future.set_result(line)
                        continue
                    if self.config.wire_mode == "at_raw" and first == bytes((self.config.slave_id,)):
                        function = await self.reader.readexactly(1)
                        length = await self.reader.readexactly(1)
                        remaining = 2 if function[0] & 0x80 else length[0] + 2
                        if remaining > 252:
                            raise ProtocolError("oversized_raw_modbus")
                        data = first + function + length + await self.reader.readexactly(remaining)
                        if self.raw_future and not self.raw_future.done():
                            self.raw_future.set_result(data)
                        continue
                    tid, code, address, function, payload = await read_frame(self.reader, first)
                _LOGGER.debug(
                    "%s RX tid=%s code=%s address=%s function=%s payload_bytes=%s",
                    self.config.name, tid, code, address, function, len(payload),
                )
                if function == 1 and self.heartbeat_reply is not None:
                    expected_tid, future = self.heartbeat_reply
                    if tid == expected_tid and not future.done():
                        future.set_result(None)
                pending = self.pending.get(tid)
                if pending:
                    expected_function, expected_code, expected_address, future = pending
                    if (function, code, address) == (expected_function, expected_code, expected_address):
                        if not future.done():
                            future.set_result(payload)
        except asyncio.CancelledError:
            raise
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
            OSError,
            ConnectionError,
            ProtocolError,
            UnicodeError,
        ) as exc:
            error = exc
            _LOGGER.debug(
                "Receive stopped for %s (%s): %s",
                self.config.name, type(exc).__name__, exc,
            )
        finally:
            self.closed = True
            if self.heartbeat_task is not None:
                self.heartbeat_task.cancel()
            for _, _, _, future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            for future in (self.raw_future, self.at_future):
                if future is not None and not future.done():
                    future.set_exception(error)
            if self.heartbeat_reply is not None:
                _, future = self.heartbeat_reply
                if not future.done():
                    future.set_exception(error)
            self.writer.close()

    async def _exchange(self, function: int, payload: bytes, code: int | None = None,
                        address: int | None = None) -> bytes:
        if self.closed:
            raise ConnectionError("collector_disconnected")
        self.tid = self.tid % 65535 + 1
        tid = self.tid
        devcode = self.config.devcode if code is None else code
        collector_address = self.config.collector_address if address is None else address
        future = asyncio.get_running_loop().create_future()
        self.pending[tid] = (function, devcode, collector_address, future)
        try:
            _LOGGER.debug(
                "%s TX tid=%s code=%s address=%s function=%s",
                self.config.name, tid, devcode, collector_address, function,
            )
            self.writer.write(frame(tid, function, payload, devcode, collector_address))
            await asyncio.wait_for(self.writer.drain(), self.timeout)
            return await asyncio.wait_for(future, self.timeout)
        except (TimeoutError, ConnectionError):
            await self.close()
            raise
        finally:
            self.pending.pop(tid, None)
            if not future.done():
                future.cancel()

    async def read_identity(self) -> str:
        """Read the logger identity for onboarding without assuming its PN."""
        async with self.lock:
            if self.config.wire_mode == "framed":
                if self.heartbeat_task is None:
                    await self._send_heartbeat(wait_for_reply=True)
                    self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                payload = await self._exchange(2, b"\x02", code=1, address=1)
                if not payload.startswith(b"\x00\x02"):
                    raise ProtocolError("invalid_identity_response")
                pn = payload[2:].rstrip(b"\0").decode("ascii")
            else:
                self.at_future = asyncio.get_running_loop().create_future()
                try:
                    self.writer.write(b"AT+DTUPN?\r\n")
                    await self.writer.drain()
                    line = await asyncio.wait_for(self.at_future, self.timeout)
                    match = re.fullmatch(rb"AT\+DTUPN\s*[:=]\s*([A-Z]\d{13,17})\s*", line)
                    if not match:
                        raise ProtocolError("invalid_at_identity")
                    pn = match[1].decode()
                finally:
                    self.at_future = None
            if not re.fullmatch(r"[A-Z]\d{13,17}", pn):
                raise ProtocolError("invalid_collector_pn")
            return pn

    async def identify(self) -> str:
        pn = await self.read_identity()
        if pn != self.config.pn:
            raise ProtocolError("collector_pn_mismatch")
        return pn

    async def read_holding(self, start: int, count: int) -> list[int]:
        request = read_request(self.config.slave_id, start, count)
        async with self.lock:
            if self.config.wire_mode == "at_raw":
                self.raw_future = asyncio.get_running_loop().create_future()
                try:
                    self.writer.write(request)
                    await asyncio.wait_for(self.writer.drain(), self.timeout)
                    reply = await asyncio.wait_for(self.raw_future, self.timeout)
                except (TimeoutError, ConnectionError):
                    await self.close()
                    raise
                finally:
                    self.raw_future = None
            else:
                reply = await self._exchange(4, request)
            return read_response(reply, self.config.slave_id, count)


async def request_callback(ip: str, advertised_ip: str, tcp_port: int, udp_port: int) -> bool:
    message = f"set>server={advertised_ip}:{tcp_port};".encode("ascii")
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        await loop.sock_sendto(sock, message, (ip, udp_port))
        try:
            data, peer = await asyncio.wait_for(loop.sock_recvfrom(sock, 512), 1)
        except TimeoutError:
            return False
        return peer[0] == ip and re.fullmatch(rb"rsp>server=\d+;", data.strip()) is not None
