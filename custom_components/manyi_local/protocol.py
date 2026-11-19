"""Read-only EyeBond and Modbus framing."""

import struct
from datetime import datetime, timezone


class ProtocolError(Exception):
    """Raised when a collector frame or Modbus response is invalid."""


class ModbusException(ProtocolError):
    """Raised when the inverter returns a Modbus exception."""

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"modbus_exception_{code}")


def crc16(data: bytes) -> int:
    crc = 65535
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def read_request(slave: int, start: int, count: int) -> bytes:
    if not 1 <= slave <= 247 or not 1 <= count <= 125 or not 0 <= start <= 65536 - count:
        raise ValueError("invalid_read_range")
    data = struct.pack(">BBHH", slave, 3, start, count)
    return data + struct.pack("<H", crc16(data))


def read_response(data: bytes, slave: int, count: int) -> list[int]:
    if len(data) < 5 or crc16(data[:-2]) != int.from_bytes(data[-2:], "little"):
        raise ProtocolError("bad_modbus_crc_or_length")
    if data[0] != slave:
        raise ProtocolError("wrong_slave")
    if data[1] == 0x83 and len(data) == 5:
        raise ModbusException(data[2])
    if data[1] != 3 or data[2] != count * 2 or len(data) != count * 2 + 5:
        raise ProtocolError("wrong_modbus_response")
    return list(struct.unpack(">" + "H" * count, data[3:-2]))


def frame(tid: int, function: int, payload: bytes, devcode: int = 1, address: int = 255) -> bytes:
    return struct.pack(">HHHBB", tid, devcode, len(payload) + 2, address, function) + payload


def heartbeat(tid: int, devcode: int = 0, address: int = 1) -> bytes:
    now = datetime.now(timezone.utc)
    payload = bytes((now.year - 2000, now.month, now.day, now.hour, now.minute, now.second))
    payload += struct.pack(">H", 60)
    return frame(tid, 1, payload, devcode, address)


async def read_frame(reader, first: bytes = b"") -> tuple[int, int, int, int, bytes]:
    header = first + await reader.readexactly(8 - len(first))
    tid, code, length, address, function = struct.unpack(">HHHBB", header)
    if not 2 <= length <= 4096:
        raise ProtocolError(
            f"invalid_frame_length: length={length}, header={header.hex()}"
        )
    payload = await reader.readexactly(length - 2)
    return tid, code, address, function, payload
