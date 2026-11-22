import asyncio

import pytest

from custom_components.manyi_local.const import (
    CONF_ADVERTISED_IP,
    CONF_INVERTERS,
    CONF_IP,
    CONF_NAME,
    CONF_PN,
    CONF_POLL_SECONDS,
    CONF_SLAVE_ID,
    CONF_TCP_PORT,
    CONF_UDP_PORT,
    CONF_WIRE_MODE,
)
from custom_components.manyi_local.hub import CollectorConfig, ManyiHub
from custom_components.manyi_local.protocol import (
    ModbusException, ProtocolError, crc16, frame, read_frame,
)
from custom_components.manyi_local.transport import CollectorSession, request_callback


PN = "I12345678901234"


def make_hub():
    return ManyiHub(
        {
            CONF_ADVERTISED_IP: "192.0.2.10",
            CONF_TCP_PORT: 8899,
            CONF_UDP_PORT: 58899,
            CONF_POLL_SECONDS: 15,
            CONF_INVERTERS: [
                {
                    CONF_NAME: "Test inverter",
                    CONF_IP: "192.0.2.20",
                    CONF_PN: PN,
                    CONF_WIRE_MODE: "framed",
                    CONF_SLAVE_ID: 4,
                }
            ],
        }
    )


class FakeSession:
    def __init__(self, fail_ranges=()):
        self.fail_ranges = set(fail_ranges)

    async def read_holding(self, start, count):
        if start in self.fail_ranges:
            raise ModbusException(2)
        registers = {
            109: 520,
            110: 65516,
            113: 85,
            114: 99,
            15205: 3500,
            15206: 520,
            15207: 12,
            15208: 600,
            15209: 40,
            16205: 3200,
            16206: 510,
            16207: 20,
            16208: 700,
            16209: 42,
            25205: 526,
            25206: 2300,
            25210: 123,
            25212: 40,
            25215: 850,
            25216: 0,
            25233: 45,
            25273: 65500,
            25274: 22,
        }
        return [registers.get(address, 0) for address in range(start, start + count)]


def test_read_values_preserves_sources_and_calculates_only_documented_estimates():
    hub = make_hub()
    config = next(iter(hub.configs.values()))
    values = asyncio.run(hub._read_values(FakeSession(), config))

    assert values["inverter_output_voltage"] == 230
    assert values["inverter_battery_voltage"] == 52.6
    assert values["inverter_current"] == 12.3
    assert values["load_current"] == 4
    assert values["ac_output_power"] == 850
    assert values["inverter_temperature"] == 45
    assert values["mppt1_pv_voltage"] == 350
    assert values["mppt1_charger_current"] == 1.2
    assert values["mppt1_charger_power"] == 600
    assert values["mppt1_estimated_output_power"] == 62.4
    assert values["bms_battery_voltage"] == 52
    assert values["bms_battery_current"] == -2
    assert values["inverter_battery_power"] == -36
    assert values["bms_soc"] == 85
    assert values["bms_soh"] == 99
    assert values["bms_calculated_power"] == -104


def test_unavailable_register_blocks_do_not_become_zero():
    hub = make_hub()
    config = next(iter(hub.configs.values()))
    values = asyncio.run(
        hub._read_values(FakeSession(fail_ranges=(109, 16205)), config)
    )

    assert values["bms_battery_voltage"] is None
    assert values["bms_calculated_power"] is None
    assert values["mppt2_pv_voltage"] is None
    assert values["mppt2_charger_power"] is None
    assert values["mppt1_charger_power"] == 600


def test_framed_logger_identity_and_read_round_trip():
    async def run():
        config = CollectorConfig(
            name="Test inverter",
            ip="127.0.0.1",
            pn=PN,
            wire_mode="framed",
            slave_id=4,
        )

        async def logger(reader, writer):
            tid, code, address, function, payload = await read_frame(reader)
            assert (code, address, function, payload[-2:]) == (0, 1, 1, b"\x00\x3c")
            writer.write(frame(tid, 1, b"", 0, 1))
            await writer.drain()

            tid, code, address, function, payload = await read_frame(reader)
            assert (code, address, function, payload) == (1, 1, 2, b"\x02")
            writer.write(frame(tid, 2, b"\x00\x02" + PN.encode(), code, address))
            await writer.drain()

            tid, code, address, function, payload = await read_frame(reader)
            assert function == 4
            response = bytes((4, 3, 2, 0, 42))
            response += crc16(response).to_bytes(2, "little")
            writer.write(frame(tid, function, response, code, address))
            await writer.drain()
            await reader.read()
            writer.close()

        server = await asyncio.start_server(logger, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        session = CollectorSession(reader, writer, config, 1)
        try:
            assert await session.identify() == PN
            assert await session.read_holding(16209, 1) == [42]
        finally:
            await session.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_udp_callback_request_accepts_logger_acknowledgement():
    async def run():
        loop = asyncio.get_running_loop()

        class LoggerProtocol(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, address):
                assert data == b"set>server=127.0.0.1:8899;"
                self.transport.sendto(b"rsp>server=2;", address)

        transport, _ = await loop.create_datagram_endpoint(
            LoggerProtocol, local_addr=("127.0.0.1", 0)
        )
        try:
            port = transport.get_extra_info("sockname")[1]
            assert await request_callback("127.0.0.1", "127.0.0.1", 8899, port)
        finally:
            transport.close()

    asyncio.run(run())


def test_invalid_frame_reports_header_without_accepting_bad_length():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(bytes.fromhex("000100010001ff04"))
        with pytest.raises(
            ProtocolError, match="invalid_frame_length: length=1, header=000100010001ff04"
        ):
            await read_frame(reader)

    asyncio.run(run())


def test_read_timeout_reports_register_range_and_propagates(caplog):
    class TimedOutSession:
        async def read_holding(self, start, count):
            raise TimeoutError

    hub = make_hub()
    config = next(iter(hub.configs.values()))
    with pytest.raises(TimeoutError):
        asyncio.run(hub._read_words(TimedOutSession(), config, 16205, 5))

    assert "registers 16205..16209 [TimeoutError]" in caplog.text


def test_identity_waits_for_initial_heartbeat_response():
    async def run():
        reader = asyncio.StreamReader()

        class Writer:
            def __init__(self):
                self.packets = []

            def write(self, packet):
                self.packets.append(packet)

            async def drain(self):
                pass

            def close(self):
                reader.feed_eof()

            async def wait_closed(self):
                pass

        writer = Writer()
        config = next(iter(make_hub().configs.values()))
        session = CollectorSession(reader, writer, config, 1)
        identify = asyncio.create_task(session.identify())
        try:
            for _ in range(10):
                await asyncio.sleep(0)
            assert len(writer.packets) == 1, "Identity sent before heartbeat acknowledgement"
            assert writer.packets[0][7] == 1
            heartbeat_tid = int.from_bytes(writer.packets[0][:2], "big")
            reader.feed_data(frame(heartbeat_tid + 10, 1, PN.encode(), 0, 1))
            for _ in range(10):
                await asyncio.sleep(0)
            assert len(writer.packets) == 1
            reader.feed_data(frame(heartbeat_tid, 1, PN.encode(), 256, 1))

            for _ in range(10):
                await asyncio.sleep(0)
            assert len(writer.packets) == 2
            assert writer.packets[1][7] == 2
            identity_tid = int.from_bytes(writer.packets[1][:2], "big")
            reader.feed_data(frame(identity_tid, 2, b"\x00\x02" + PN.encode(), 1, 1))
            assert await identify == PN
        finally:
            identify.cancel()
            await asyncio.gather(identify, return_exceptions=True)
            await session.close()

    asyncio.run(run())


def test_missing_initial_heartbeat_closes_session_before_identity_query():
    async def run():
        reader = asyncio.StreamReader()

        class Writer:
            def __init__(self):
                self.packets = []
                self.closed = False

            def write(self, packet):
                self.packets.append(packet)

            async def drain(self):
                pass

            def close(self):
                self.closed = True
                reader.feed_eof()

            async def wait_closed(self):
                pass

        writer = Writer()
        config = next(iter(make_hub().configs.values()))
        session = CollectorSession(reader, writer, config, 0.02)
        try:
            with pytest.raises(TimeoutError, match="initial_heartbeat_reply_timeout"):
                await session.identify()
            assert session.closed
            assert writer.closed
            assert [packet[7] for packet in writer.packets] == [1]
            assert session.heartbeat_task is None
        finally:
            await session.close()

    asyncio.run(run())
