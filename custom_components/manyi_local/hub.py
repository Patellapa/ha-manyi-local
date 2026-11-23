"""Own the shared callback listener and collect read-only inverter telemetry."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from .const import (
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
    DEFAULT_TIMEOUT_SECONDS,
)
from .protocol import ModbusException, ProtocolError
from .settings import SETTINGS, SETTING_ADDRESSES
from .transport import CollectorSession, close_writer, request_callback

_LOGGER = logging.getLogger(__name__)
_RETRY_SECONDS = 30
_READ_GAP_SECONDS = 0.15


@dataclass(frozen=True)
class CollectorConfig:
    name: str
    ip: str
    pn: str
    wire_mode: str
    slave_id: int
    devcode: int = 1
    collector_address: int = 255


class ManyiHub:
    def __init__(self, data: dict) -> None:
        self.advertised_ip = data[CONF_ADVERTISED_IP]
        self.tcp_port = data[CONF_TCP_PORT]
        self.udp_port = data[CONF_UDP_PORT]
        self.poll_seconds = data[CONF_POLL_SECONDS]
        self.configs = {
            item[CONF_IP]: CollectorConfig(
                name=item[CONF_NAME],
                ip=item[CONF_IP],
                pn=item[CONF_PN],
                wire_mode=item[CONF_WIRE_MODE],
                slave_id=item[CONF_SLAVE_ID],
            )
            for item in data[CONF_INVERTERS]
        }
        self.states = {
            config.ip: {"connected": False, "values": {}}
            for config in self.configs.values()
        }
        self._listeners = {ip: set() for ip in self.configs}
        self._sessions = {}
        self._admitting = set()
        self._connection_tasks = set()
        self._callback_tasks = []
        self._server = None
        self._stopping = False
        self.settings_raw = {ip: {} for ip in self.configs}
        self._settings_due = {ip: {} for ip in self.configs}
        self.value_updated = {ip: {} for ip in self.configs}
        self.settings_errors = {ip: {} for ip in self.configs}

    async def async_start(self) -> None:
        self._stopping = False
        self._server = await asyncio.start_server(self._accept, "0.0.0.0", self.tcp_port)
        self._callback_tasks = [
            asyncio.create_task(self._request_callback_loop(config))
            for config in self.configs.values()
        ]
        _LOGGER.info("MANYi callback listener started on TCP port %s", self.tcp_port)

    async def async_stop(self) -> None:
        """Close clients before waiting for the TCP server to finish shutdown."""
        self._stopping = True
        server = self._server
        if server is not None:
            server.close()
            # Also cover accepted transports whose callback task has not run yet.
            if hasattr(server, "close_clients"):
                server.close_clients()
        tasks = tuple(self._callback_tasks) + tuple(self._connection_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(session.close() for session in tuple(self._sessions.values())),
                             return_exceptions=True)
        if server is not None:
            await server.wait_closed()
        self._server = None
        self._callback_tasks.clear()
        self._connection_tasks.clear()
        self._sessions.clear()
        self._admitting.clear()
        for state in self.states.values():
            state["connected"] = False

    def async_add_listener(self, ip: str, callback):
        self._listeners[ip].add(callback)
        return lambda: self.async_remove_listener(ip, callback)

    def async_remove_listener(self, ip: str, callback) -> None:
        self._listeners[ip].discard(callback)

    def _notify(self, ip: str) -> None:
        for callback in tuple(self._listeners[ip]):
            callback()

    async def _request_callback_loop(self, config: CollectorConfig) -> None:
        while True:
            if not self.states[config.ip]["connected"]:
                try:
                    _LOGGER.debug(
                        "Requesting callback from %s (%s) to %s:%s",
                        config.name, config.ip, self.advertised_ip, self.tcp_port,
                    )
                    acknowledged = await request_callback(
                        config.ip, self.advertised_ip, self.tcp_port, self.udp_port
                    )
                    if acknowledged:
                        _LOGGER.debug("Logger %s replied to the callback request", config.name)
                    else:
                        _LOGGER.debug("No valid UDP callback reply from %s", config.name)
                except OSError as exc:
                    _LOGGER.warning("Cannot request callback from %s: %s", config.name, exc)
            await asyncio.sleep(_RETRY_SECONDS)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connection_tasks.add(task)
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else None
        config = self.configs.get(ip)
        session = None
        if self._stopping or config is None or ip in self._admitting or (
            ip in self._sessions and not self._sessions[ip].closed
        ):
            _LOGGER.debug(
                "Rejecting TCP callback from %s: unknown IP or existing session", ip
            )
            try:
                await close_writer(writer)
            finally:
                if task is not None:
                    self._connection_tasks.discard(task)
            return

        self._admitting.add(ip)
        stage = "identity"
        try:
            _LOGGER.debug(
                "Identifying %s (%s), protocol=%s, slave=%s",
                config.name, ip, config.wire_mode, config.slave_id,
            )
            session = CollectorSession(reader, writer, config, DEFAULT_TIMEOUT_SECONDS)
            await session.identify()
            self._sessions[ip] = session
            self.states[ip]["session_started"] = datetime.now(timezone.utc).isoformat()
            self.states[ip]["connected"] = True
            self._notify(ip)
            _LOGGER.info("Connected to %s", config.name)
            stage = "polling"
            while not session.closed:
                values = await self._read_values(session, config)
                self._publish_values(ip, values)
                self._merge_settings(ip, self.states[ip]["values"])
                self._notify(ip)
                await self._read_settings(session, config)
                self._merge_settings(ip, self.states[ip]["values"])
                self._notify(ip)
                # Wake immediately if the reader detects a lost dongle, rather
                # than reporting connected until the next polling deadline.
                await asyncio.wait({session.reader_task}, timeout=self.poll_seconds)
        except asyncio.CancelledError:
            raise
        except (
            OSError,
            TimeoutError,
            ConnectionError,
            EOFError,
            ProtocolError,
            ValueError,
            UnicodeError,
        ) as exc:
            log = _LOGGER.debug if self._stopping else _LOGGER.warning
            log(
                "Connection to %s (%s) ended during %s [%s]: %s",
                config.name, ip, stage, type(exc).__name__, exc,
            )
        finally:
            if session is not None:
                await session.close()
            await close_writer(writer)
            self._admitting.discard(ip)
            if ip in self._sessions and self._sessions[ip] is session:
                self._sessions.pop(ip, None)
            self.states[ip]["connected"] = False
            self._notify(ip)
            if task is not None:
                self._connection_tasks.discard(task)

    def _publish_values(self, ip: str, values: dict) -> None:
        """Commit a completed live read; a failed transport never erases it.

        Explicit missing measurements (e.g. zero-voltage BMS) still invalidate
        their values, rather than masking battery communication failures.
        """
        self.states[ip]["values"].update(values)
        now = datetime.now(timezone.utc).isoformat()
        for key, value in values.items():
            if value is not None:
                self.value_updated[ip][key] = now

    def _merge_settings(self, ip: str, values: dict) -> None:
        raw = self.settings_raw[ip]
        for setting in SETTINGS:
            value = raw.get(setting.address)
            values[setting.key] = setting.decode(value) if value is not None else None

    async def _read_settings(self, session: CollectorSession, config: CollectorConfig) -> None:
        """Read up to four individual addresses after publishing live telemetry.

        Never read across undocumented gaps. Retry optional addresses no sooner
        than five minutes, including after a timeout/reconnection.
        """
        ip = config.ip
        now = asyncio.get_running_loop().time()
        due = self._settings_due[ip]
        addresses = sorted(SETTING_ADDRESSES, key=lambda address: due.get(address, 0))
        for address in addresses[:4]:
            if due.get(address, 0) > now:
                break
            due[address] = now + 300
            self.settings_raw[ip].setdefault(address, None)
            try:
                words = await self._read_words(session, config, address, 1)
                if words is not None:
                    self.settings_raw[ip][address] = words[0]
                    self.settings_errors[ip].pop(address, None)
                    timestamp = datetime.now(timezone.utc).isoformat()
                    for setting in SETTINGS:
                        if setting.address == address:
                            self.value_updated[ip][setting.key] = timestamp
                else:
                    self.settings_errors[ip][address] = "modbus_read_rejected"
            except (OSError, TimeoutError, EOFError, ProtocolError) as exc:
                self.settings_errors[ip][address] = str(exc) or type(exc).__name__
                _LOGGER.debug("Optional setting %s unavailable for %s", address, config.name)
                break

    async def _read_words(self, session: CollectorSession, config: CollectorConfig,
                          start: int, count: int) -> list[int] | None:
        _LOGGER.debug(
            "Reading %s registers %s..%s", config.name, start, start + count - 1
        )
        try:
            result = await session.read_holding(start, count)
        except ModbusException as exc:
            _LOGGER.debug(
                "Logger %s rejected read %s..%s: %s",
                config.name,
                start,
                start + count - 1,
                exc,
            )
            return None
        except (OSError, TimeoutError, EOFError, ProtocolError) as exc:
            _LOGGER.warning(
                "Read failed for %s (%s), registers %s..%s [%s]: %s",
                config.name, config.ip, start, start + count - 1,
                type(exc).__name__, exc,
            )
            raise
        await asyncio.sleep(_READ_GAP_SECONDS)
        return result

    async def _read_values(self, session: CollectorSession, config: CollectorConfig) -> dict:
        core = await self._read_words(session, config, 25205, 12)
        temperature = await self._read_words(session, config, 25233, 1)
        battery = await self._read_words(session, config, 25273, 2)
        mppt = {
            channel: await self._read_words(session, config, base + 5, 5)
            for channel, base in ((1, 15200), (2, 16200))
        }
        bms = await self._read_words(session, config, 109, 6)
        # The inverter can return zero BMS telemetry with a default SOH of 100
        # when battery communication is absent. Zero voltage is not a valid
        # live battery measurement; do not publish that block as real data.
        if bms is not None and bms[0] == 0:
            bms = None

        values = {
            "inverter_output_voltage": _metric(core, 1, 0.1),
            "inverter_current": _metric(core, 5, 0.1),
            "load_current": _metric(core, 7, 0.1),
            "ac_output_power": _metric(core, 10, signed=True),
            "inverter_temperature": _metric(temperature, 0, signed=True),
            "inverter_battery_power": _metric(battery, 0, signed=True),
            "inverter_battery_voltage": _metric(core, 0, 0.1),
            "inverter_battery_current": _metric(battery, 1, signed=True),
            "bms_battery_voltage": _metric(bms, 0, 0.1),
            "bms_battery_current": _metric(bms, 1, 0.1, signed=True),
            "bms_soc": _metric(bms, 4),
            "bms_soh": _metric(bms, 5),
        }
        voltage = values["bms_battery_voltage"]
        current = values["bms_battery_current"]
        values["bms_calculated_power"] = (
            round(voltage * current, 2) if voltage is not None and current is not None else None
        )
        for channel, words in mppt.items():
            prefix = f"mppt{channel}_"
            values[prefix + "pv_voltage"] = _metric(words, 0, 0.1)
            values[prefix + "battery_voltage"] = _metric(words, 1, 0.1)
            values[prefix + "charger_current"] = _metric(words, 2, 0.1)
            values[prefix + "charger_power"] = _metric(words, 3)
            values[prefix + "radiator_temperature"] = _metric(words, 4, signed=True)
            mppt_voltage = values[prefix + "battery_voltage"]
            charge_current = values[prefix + "charger_current"]
            values[prefix + "estimated_output_power"] = (
                round(mppt_voltage * charge_current, 2)
                if mppt_voltage is not None and charge_current is not None
                else None
            )
        return values


def _metric(words: list[int] | None, offset: int, scale: float = 1,
            signed: bool = False) -> int | float | None:
    if words is None:
        return None
    value = words[offset]
    if signed and value >= 32768:
        value -= 65536
    scaled = value * scale
    return round(scaled, 2) if scale != 1 else value
