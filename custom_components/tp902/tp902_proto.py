"""TP902 BLE thermometer protocol library.

Single-file library with transport abstraction. No external dependencies.
Compatible with CPython and MicroPython.
"""
from __future__ import annotations

try:
    from time import ticks_ms, ticks_diff, ticks_add  # type: ignore
except ImportError:
    from time import monotonic

    def ticks_ms():
        return int(monotonic() * 1000)

    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, b):
        return a + b


# --- BLE UUIDs ---

SERVICE_UUID = "1086fff0-3343-4817-8bb2-b32206336ce8"
WRITE_UUID = "1086fff1-3343-4817-8bb2-b32206336ce8"
NOTIFY_UUID = "1086fff2-3343-4817-8bb2-b32206336ce8"

# --- TX command codes ---

CMD_AUTH = 0x01
CMD_BACKLIGHT_ON = 0x02
CMD_SET_UNITS = 0x20
CMD_SET_SOUND = 0x21
CMD_SET_ALARM = 0x23
CMD_GET_ALARM = 0x24
CMD_GET_STATUS = 0x26
CMD_SNOOZE_ALARM = 0x27
CMD_TIME_SYNC = 0x28
CMD_GET_FW = 0x41

# --- RX command codes ---

RX_TEMP_BROADCAST = 0x30
RX_TEMP_ACTUAL = 0x25
RX_STATUS = 0x26
RX_ALARM = 0x24
RX_FW_VERSION = 0x41
RX_AUTH = 0x01
RX_ERROR = 0xE0

# --- Value constants ---

UNITS_C = 0x0C
UNITS_F = 0x0F
SOUND_ON = 0x0C
SOUND_OFF = 0x0F
ALARM_OFF = 0x00
ALARM_TARGET = 0x0A
ALARM_RANGE = 0x82

# --- Auth ---
# Fixed auth packet (deterministic, seed=254, 6 lookup tables A-F × 16 entries).
# The auth mechanism uses 3 random int32s, indexes into tables by nibble,
# and swaps pairs based on LSB. For random auth (replay attack resistance),
AUTH_PACKET = b'\x01\x09\x99\xa8\x89\x3c\x66\x81\x75\x0d\xe3\x5c'

# --- Epoch offset (2020-01-01 00:00:00 UTC) ---

EPOCH_2020 = 1577836800


# --- Data classes ---


class Temperature:
    """Single probe temperature reading."""
    __slots__ = ('channel', 'value')

    def __init__(self, channel, value):
        self.channel = channel  # int 1-6
        self.value = value      # float (°C) or None if probe absent

    def __repr__(self):
        if self.value is None:
            return "T%d=---" % self.channel
        return "T%d=%.1f" % (self.channel, self.value)


class TemperatureBroadcast:
    """Periodic temperature broadcast (cmd 0x30)."""
    __slots__ = ('battery', 'units', 'alarms', 'temperatures')

    def __init__(self, battery, units, alarms, temperatures):
        self.battery = battery            # int 0-100
        self.units = units                # 'C' or 'F'
        self.alarms = alarms              # int (bitmask)
        self.temperatures = temperatures  # list of Temperature (6 items)

    def __repr__(self):
        temps = ' '.join(repr(t) for t in self.temperatures)
        return "Broadcast(bat=%d%% units=%s alarms=0x%02x %s)" % (
            self.battery, self.units, self.alarms, temps)


class TemperatureActual:
    """Actual temperature reading (cmd 0x25). Always in °C, no unit conversion."""
    __slots__ = ('probe_count', 'alarms', 'temperatures')

    def __init__(self, probe_count, alarms, temperatures):
        self.probe_count = probe_count  # int
        self.alarms = alarms            # int (bitmask)
        self.temperatures = temperatures  # list of Temperature

    def __repr__(self):
        temps = ' '.join(repr(t) for t in self.temperatures)
        return "Actual(probes=%d alarms=0x%02x %s)" % (
            self.probe_count, self.alarms, temps)


class AlarmConfig:
    """Alarm configuration for a channel (cmd 0x24)."""
    __slots__ = ('channel', 'mode', 'value1', 'value2')

    def __init__(self, channel, mode, value1, value2):
        self.channel = channel  # int 1-6
        self.mode = mode        # ALARM_OFF / ALARM_TARGET / ALARM_RANGE
        self.value1 = value1    # float or None
        self.value2 = value2    # float or None

    def __repr__(self):
        if self.mode == ALARM_OFF:
            return "Alarm(ch%d OFF)" % self.channel
        if self.mode == ALARM_TARGET:
            return "Alarm(ch%d TARGET=%.1f)" % (self.channel, self.value1 or 0)
        if self.mode == ALARM_RANGE:
            return "Alarm(ch%d RANGE=%.1f-%.1f)" % (
                self.channel, self.value2 or 0, self.value1 or 0)
        return "Alarm(ch%d mode=0x%02x)" % (self.channel, self.mode)


class FirmwareVersion:
    """Firmware version (cmd 0x41)."""
    __slots__ = ('major', 'minor', 'patch', 'build')

    def __init__(self, major, minor, patch, build):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.build = build

    def __repr__(self):
        return "FW(%s)" % str(self)

    def __str__(self):
        return "%d.%d.%02x.%02x" % (self.major, self.minor, self.patch, self.build)


class DeviceStatus:
    """Device status/config (cmd 0x26). DATA[1]: 0x0c=beeper ON, 0x0f=beeper OFF."""
    __slots__ = ('units', 'beeper', 'battery')

    def __init__(self, units, beeper, battery):
        self.units = units      # 'C' or 'F'
        self.beeper = beeper    # bool (True=ON, False=OFF)
        self.battery = battery  # int 0-100

    def __repr__(self):
        beeper_str = "ON" if self.beeper else "OFF"
        return "Status(units=%s beeper=%s bat=%d%%)" % (
            self.units, beeper_str, self.battery)


class AuthResponse:
    """Auth handshake response (cmd 0x01)."""
    __slots__ = ('data',)

    def __init__(self, data):
        self.data = data  # raw bytes (2 bytes, mapping not fully known)

    def __repr__(self):
        return "Auth(data=%s)" % self.data.hex()


# --- Packet helpers ---


def decode_temp_bcd(raw):
    """Decode 2-byte BCD temperature.

    :param raw: 2 bytes
    :returns: float (°C) or None if probe absent (0xFFFF)
    """
    if raw[0] == 0xFF and raw[1] == 0xFF:
        return None
    neg = bool(raw[0] & 0x80)
    b0 = raw[0] & 0x7F
    b1 = raw[1]
    # BCD: b0 = [hundreds_tens][tens_ones], b1 = [ones_digit][tenths]
    hundreds = (b0 >> 4) * 100
    tens = (b0 & 0x0F) * 10
    ones = (b1 >> 4)
    tenths = (b1 & 0x0F)
    value = (hundreds + tens + ones) + tenths / 10.0
    if neg:
        value = -value
    return value


def encode_temp_bcd(value):
    """Encode float temperature to 2-byte BCD.

    :param value: float (°C), range -999.9 to 999.9
    :returns: bytes (2 bytes)
    """
    neg = value < 0
    val = abs(value)
    tenths_total = int(val * 10 + 0.5)  # round
    ones_total = tenths_total // 10
    tenths = tenths_total % 10
    ones = ones_total % 10
    tens = (ones_total // 10) % 10
    hundreds = (ones_total // 100) % 10
    b0 = (hundreds << 4) | tens
    b1 = (ones << 4) | tenths
    if neg:
        b0 |= 0x80
    return bytes([b0 & 0xFF, b1 & 0xFF])


def build_packet(cmd, payload=b''):
    """Build TP902 packet frame: CMD LEN DATA CHECKSUM.

    :param cmd: command byte
    :param payload: data bytes
    :returns: complete packet bytes
    """
    pkt_len = len(payload)
    header = bytes([cmd, pkt_len])
    checksum = (sum(header) + sum(payload)) & 0xFF
    return header + payload + bytes([checksum])


def verify_checksum(data):
    """Verify packet checksum.

    :param data: raw packet bytes (at least 3 bytes)
    :returns: bool
    """
    if len(data) < 3:
        return False
    pkt_len = data[1]
    if len(data) < 2 + pkt_len + 1:
        return False
    expected = sum(data[0:2 + pkt_len]) & 0xFF
    return expected == data[2 + pkt_len]



def _parse_units(raw_byte):
    """Parse units byte to string."""
    if raw_byte == UNITS_C:
        return 'C'
    if raw_byte == UNITS_F:
        return 'F'
    return '0x%02x' % raw_byte


# --- Transport abstraction ---


class TP902Transport:
    """Abstract BLE transport for TP902.

    Subclass and implement send() and receive() for your platform.
    """

    def send(self, data):
        """Write data (bytes) to BLE write characteristic.

        :param data: bytes to send
        :raises: on failure
        """
        raise NotImplementedError

    def receive(self, timeout_ms):
        """Block until BLE notification arrives or timeout.

        :param timeout_ms: max wait time in milliseconds
        :returns: bytes (notification payload) or None on timeout
        """
        raise NotImplementedError


# --- Main protocol class ---


class TP902:
    """TP902 thermometer protocol handler.

    Usage::

        transport = MyBLETransport(...)
        tp = TP902(transport, on_temperature=my_callback)
        tp.authenticate()
        tp.sync_time()
        # continuous operation:
        while True:
            tp.process()
    """

    def __init__(self, transport, on_temperature=None):
        """
        :param transport: TP902Transport instance
        :param on_temperature: callback(TemperatureBroadcast) for 0x30 broadcasts
        """
        self._transport = transport
        self._on_temperature = on_temperature

    # --- Public API: request-response ---

    def authenticate(self, timeout_ms=5000):
        """Send auth handshake, wait for response.

        :param timeout_ms: response timeout
        :returns: AuthResponse or None on timeout
        """
        self._transport.send(AUTH_PACKET)
        return self._wait_response(RX_AUTH, timeout_ms)

    def backlight_on(self):
        """Lights up LCD same as button push

        """
        self._send(CMD_BACKLIGHT_ON)

    def get_firmware_version(self, timeout_ms=5000):
        """Request firmware version.

        :returns: FirmwareVersion or None on timeout
        """
        self._send(CMD_GET_FW)
        return self._wait_response(RX_FW_VERSION, timeout_ms)

    def get_alarm(self, channel, timeout_ms=5000):
        """Request alarm config for channel.

        :param channel: 1-6
        :returns: AlarmConfig or None on timeout
        """
        self._send(CMD_GET_ALARM, bytes([channel]))
        return self._wait_response(RX_ALARM, timeout_ms)

    def get_status(self, timeout_ms=5000):
        """Request device status (units, flags, battery).

        :returns: DeviceStatus or None on timeout
        """
        self._send(CMD_GET_STATUS)
        return self._wait_response(RX_STATUS, timeout_ms)

    # --- Public API: fire-and-forget ---

    def snooze_alarm(self):
        """Snoze beeping alarm until next trigger
        """
        self._send(CMD_SNOOZE_ALARM)

    def set_units(self, celsius=True):
        """Set display units.

        :param celsius: True for °C, False for °F
        """
        self._send(CMD_SET_UNITS, bytes([UNITS_C if celsius else UNITS_F]))

    def set_sound_alarm(self, enabled=True):
        """Enable/disable audible alarm.

        :param enabled: True to enable
        """
        self._send(CMD_SET_SOUND, bytes([SOUND_ON if enabled else SOUND_OFF]))

    def set_alarm(self, channel, mode=ALARM_OFF, value1=None, value2=None):
        """Set alarm for channel.

        :param channel: 1-6
        :param mode: ALARM_OFF, ALARM_TARGET, or ALARM_RANGE
        :param value1: target temp (TARGET) or high temp (RANGE)
        :param value2: low temp (RANGE only)
        """
        if mode == ALARM_OFF:
            t1 = b'\xff\xff'
            t2 = b'\xff\xff'
        elif mode == ALARM_TARGET:
            t1 = encode_temp_bcd(value1)
            t2 = b'\x00\x00'
        elif mode == ALARM_RANGE:
            t1 = encode_temp_bcd(value1)
            t2 = encode_temp_bcd(value2)
        else:
            t1 = b'\xff\xff'
            t2 = b'\xff\xff'
        self._send(CMD_SET_ALARM, bytes([channel, mode]) + t1 + t2)

    def sync_time(self, epoch_2020=None):
        """Sync device time.

        :param epoch_2020: seconds since 2020-01-01 UTC. If None, auto-calculated.
        """
        if epoch_2020 is None:
            try:
                from time import time
                epoch_2020 = int(time()) - EPOCH_2020
            except Exception:
                epoch_2020 = 0
        data = epoch_2020.to_bytes(4, 'little')
        self._send(CMD_TIME_SYNC, data)

    # --- Polling ---

    def process(self, timeout_ms=100):
        """Process one incoming notification.

        Call in a loop for continuous operation. Routes broadcasts to
        callbacks and returns response packets.

        :param timeout_ms: max wait time for notification
        :returns: (cmd, parsed_obj) tuple or None if timeout
        """
        raw = self._transport.receive(timeout_ms)
        if raw is None:
            return None
        return self._handle_raw(raw)

    # --- Internal ---

    def _send(self, cmd, payload=b''):
        pkt = build_packet(cmd, payload)
        self._transport.send(pkt)

    def _wait_response(self, expected_cmd, timeout_ms):
        """Wait for specific response cmd. Routes other packets while waiting."""
        deadline = ticks_add(ticks_ms(), timeout_ms)
        while True:
            remaining = ticks_diff(deadline, ticks_ms())
            if remaining <= 0:
                return None
            raw = self._transport.receive(remaining)
            if raw is None:
                return None
            cmd, obj = self._handle_raw(raw)
            if cmd == expected_cmd:
                return obj

    def _handle_raw(self, raw):
        """Parse and route raw notification bytes."""
        if len(raw) < 3:
            return (0, None)
        cmd = raw[0]
        parsed = self._parse_packet(cmd, raw)
        if cmd == RX_TEMP_BROADCAST:
            if self._on_temperature:
                self._on_temperature(parsed)

        return (cmd, parsed)

    def _parse_packet(self, cmd, data):
        """Parse raw packet into appropriate data class."""
        pkt_len = data[1]

        if cmd == RX_TEMP_BROADCAST and len(data) >= 17:
            battery = data[2]
            units = _parse_units(data[3])
            alarms = data[4]
            temps = []
            for i in range(6):
                offset = 5 + i * 2
                val = decode_temp_bcd(data[offset:offset + 2])
                temps.append(Temperature(i + 1, val))
            return TemperatureBroadcast(battery, units, alarms, temps)

        if cmd == RX_TEMP_ACTUAL and pkt_len == 0x0E and len(data) >= 16:
            probe_count = data[2]
            alarms = data[3]
            temps = []
            for i in range(6):
                offset = 4 + i * 2
                val = decode_temp_bcd(data[offset:offset + 2])
                temps.append(Temperature(i + 1, val))
            return TemperatureActual(probe_count, alarms, temps)

        if cmd == RX_ALARM and pkt_len == 0x06 and len(data) >= 8:
            channel = data[2]
            mode = data[3]
            val1 = decode_temp_bcd(data[4:6])
            val2 = decode_temp_bcd(data[6:8])
            return AlarmConfig(channel, mode, val1, val2)

        if cmd == RX_FW_VERSION and pkt_len == 0x03 and len(data) >= 5:
            v = data[2:5]
            major = v[0] >> 4
            minor = v[0] & 0x0F
            patch = v[1]
            build = v[2]
            return FirmwareVersion(major, minor, patch, build)

        if cmd == RX_STATUS and pkt_len == 0x05 and len(data) >= 7:
            units = _parse_units(data[2])
            beeper = data[3] == 0x0C  # 0x0c=ON, 0x0f=OFF
            battery = data[4]
            return DeviceStatus(units, beeper, battery)

        if cmd == RX_AUTH and pkt_len == 0x02 and len(data) >= 4:
            return AuthResponse(bytes(data[2:4]))

        # Unknown or unparsed - return raw data bytes
        return bytes(data[2:2 + pkt_len])