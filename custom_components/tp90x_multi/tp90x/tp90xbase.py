"""TP90x BLE thermometer protocol library.

Library with transport abstraction. No external dependencies.
Compatible with CPython and MicroPython.
Forked from petrkr/thermopro-tp902:master
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from .enums import AlarmMode, SearchMode

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
        self.temperatures = temperatures  # list of Temperature (based on number of probes)

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
        if self.mode == TP90xBase.ALARM_OFF:
            return "Alarm(ch%d OFF)" % self.channel
        if self.mode == TP90xBase.ALARM_TARGET:
            return "Alarm(ch%d TARGET=%.1f)" % (self.channel, self.value1 or 0)
        if self.mode == TP90xBase.ALARM_RANGE:
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


def _decode_temp_bcd(raw):
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


def _encode_temp_bcd(value):
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


def _build_packet(cmd, payload=b''):
    """Build TP90x packet frame: CMD LEN DATA CHECKSUM.

    :param cmd: command byte
    :param payload: data bytes
    :returns: complete packet bytes
    """
    pkt_len = len(payload)
    header = bytes([cmd, pkt_len])
    checksum = (sum(header) + sum(payload)) & 0xFF
    return header + payload + bytes([checksum])


def _verify_checksum(data):
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
    if raw_byte == TP90xBase.UNITS_C:
        return 'C'
    if raw_byte == TP90xBase.UNITS_F:
        return 'F'
    return '0x%02x' % raw_byte


# --- Transport abstraction ---


class TP90xTransport:
    """Abstract BLE transport for TP90xBase.

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


class TP90xBase(ABC):
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
    NUM_PROBES: int

    # --- Auth ---
    # Fixed auth packet (deterministic, seed=254, 6 lookup tables A-F × 16 entries).
    # The auth mechanism uses 3 random int32s, indexes into tables by nibble,
    # and swaps pairs based on LSB. For random auth (replay attack resistance),
    AUTH_PACKET = b'\x01\x09\x99\xa8\x89\x3c\x66\x81\x75\x0d\xe3\x5c'

    # --- Epoch offset (2020-01-01 00:00:00 UTC) ---

    EPOCH_2020 = 1577836800



    """TP90xBase thermometer protocol handler.

    Usage::

        transport = MyBLETransport(...)
        tp = MyTP90xModel(transport, on_temperature=my_callback)
        tp.authenticate()
        tp.sync_time()
        # continuous operation:
        while True:
            tp.process()
    """

    @classmethod
    @abstractmethod
    def model_name(cls):
        """Return model identifier for concrete subclasses."""

    @classmethod
    def connect(
        cls,
        identifier,
        *,
        by=SearchMode.ADDRESS,
        scan_timeout=10.0,
        connect_timeout=20.0,
        on_temperature=None,
    ):
        """Connect using bleak by BLE address or advertised name."""
        from bleak import BleakScanner

        if not isinstance(by, SearchMode):
            raise TypeError("by must be a SearchMode enum value")

        if by is SearchMode.ADDRESS:
            finder = BleakScanner.find_device_by_address
        elif by is SearchMode.NAME:
            finder = BleakScanner.find_device_by_name
        else:
            raise ValueError("unsupported SearchMode value: %r" % (by,))

        return cls._connect_with_bleak(
            finder,
            identifier,
            scan_timeout=scan_timeout,
            connect_timeout=connect_timeout,
            on_temperature=on_temperature,
        )

    @classmethod
    def _connect_with_bleak(
        cls,
        finder,
        identifier,
        *,
        scan_timeout=10.0,
        connect_timeout=20.0,
        on_temperature=None,
    ):
        """Create a connected instance using bleak with an internal loop thread.

        `finder` must be an async callable compatible with BleakScanner
        finder APIs (identifier, timeout=...).
        """
        import asyncio
        import queue
        import threading

        try:
            from bleak import BleakClient
        except ImportError as exc:
            raise ImportError(
                "bleak is required for connect(); install with: pip install bleak"
            ) from exc

        class _LoopThread:
            def __init__(self):
                self._ready = threading.Event()
                self._loop = None
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
                self._ready.wait()

            def _run(self):
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._ready.set()
                self._loop.run_forever()
                self._loop.close()

            def call(self, coro, timeout=None):
                fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
                return fut.result(timeout=timeout)

            def stop(self):
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=2.0)

        class _BleakTransport(TP90xTransport):
            def __init__(self, bleak_client, loop_thread):
                self._client = bleak_client
                self._loop_thread = loop_thread
                self._queue = queue.Queue()

            def send(self, data):
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.write_gatt_char(cls.WRITE_UUID, data, response=True),
                    self._loop_thread._loop,
                )
                fut.result(timeout=10.0)

            def receive(self, timeout_ms):
                try:
                    return self._queue.get(timeout=timeout_ms / 1000.0)
                except queue.Empty:
                    return None

            def on_notify(self, _handle, data):
                self._queue.put(bytes(data))

        loop_thread = _LoopThread()
        client = None
        try:
            device = loop_thread.call(
                finder(identifier, timeout=scan_timeout),
                timeout=scan_timeout + 5.0,
            )
            if device is None:
                raise TimeoutError("BLE device not found: %s" % identifier)

            client = BleakClient(device, timeout=connect_timeout, services=[cls.SERVICE_UUID])
            loop_thread.call(client.connect(), timeout=connect_timeout + 5.0)

            transport = _BleakTransport(client, loop_thread)
            loop_thread.call(client.start_notify(cls.NOTIFY_UUID, transport.on_notify), timeout=10.0)

            instance = cls(transport, on_temperature=on_temperature)
            instance._bleak_client = client
            instance._bleak_notify_uuid = cls.NOTIFY_UUID
            instance._bleak_loop_thread = loop_thread
            return instance
        except Exception:
            if client is not None:
                try:
                    loop_thread.call(client.disconnect(), timeout=5.0)
                except Exception:
                    pass
            loop_thread.stop()
            raise

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "NUM_PROBES" not in cls.__dict__:
            raise TypeError("%s must define class variable NUM_PROBES" % cls.__name__)
        if not isinstance(cls.NUM_PROBES, int) or cls.NUM_PROBES <= 0:
            raise TypeError("%s.NUM_PROBES must be a positive int" % cls.__name__)

    def __init__(self, transport, on_temperature=None):
        """
        :param transport: TP90xTransport instance
        :param on_temperature: callback(TemperatureBroadcast) for 0x30 broadcasts
        """
        self._transport = transport
        self._on_temperature = on_temperature
        self._bleak_client = None
        self._bleak_notify_uuid = None
        self._bleak_loop_thread = None

    def _validate_channel(self, channel):
        """Validate that a channel/probe index is within model bounds."""
        if not isinstance(channel, int):
            raise TypeError("channel must be an int")
        if channel < 1 or channel > self.NUM_PROBES:
            raise ValueError(
                "channel must be between 1 and %d for %s"
                % (self.NUM_PROBES, self.model_name())
            )
        return channel

    def disconnect(self):
        """Disconnect built-in bleak transport session if present."""
        if self._bleak_client is None:
            return
        try:
            if self._bleak_notify_uuid is not None:
                self._bleak_loop_thread.call(
                    self._bleak_client.stop_notify(self._bleak_notify_uuid),
                    timeout=5.0,
                )
        except Exception:
            pass
        try:
            self._bleak_loop_thread.call(self._bleak_client.disconnect(), timeout=10.0)
        finally:
            self._bleak_loop_thread.stop()
        self._bleak_client = None
        self._bleak_notify_uuid = None
        self._bleak_loop_thread = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()

    # --- Public API: request-response ---

    def authenticate(self, timeout_ms=5000):
        """Send auth handshake, wait for response.

        :param timeout_ms: response timeout
        :returns: AuthResponse or None on timeout
        """
        self._transport.send(self.AUTH_PACKET)
        return self._wait_response(self.RX_AUTH, timeout_ms)

    def backlight_on(self):
        """Lights up LCD same as button push

        """
        self._send(self.CMD_BACKLIGHT_ON)

    def get_firmware_version(self, timeout_ms=5000):
        """Request firmware version.

        :returns: FirmwareVersion or None on timeout
        """
        self._send(self.CMD_GET_FW)
        return self._wait_response(self.RX_FW_VERSION, timeout_ms)

    def get_alarm(self, channel, timeout_ms=5000):
        """Request alarm config for channel.

        :param channel: 1..NUM_PROBES
        :returns: AlarmConfig or None on timeout
        """
        channel = self._validate_channel(channel)
        self._send(self.CMD_GET_ALARM, bytes([channel]))
        return self._wait_response(self.RX_ALARM, timeout_ms)

    def get_status(self, timeout_ms=5000):
        """Request device status (units, flags, battery).

        :returns: DeviceStatus or None on timeout
        """
        self._send(self.CMD_GET_STATUS)
        return self._wait_response(self.RX_STATUS, timeout_ms)

    # --- Public API: fire-and-forget ---

    def snooze_alarm(self):
        """Snoze beeping alarm until next trigger
        """
        self._send(self.CMD_SNOOZE_ALARM)

    def set_units(self, celsius=True):
        """Set display units.

        :param celsius: True for °C, False for °F
        """
        self._send(self.CMD_SET_UNITS, bytes([self.UNITS_C if celsius else self.UNITS_F]))

    def set_sound_alarm(self, enabled=True):
        """Enable/disable audible alarm.

        :param enabled: True to enable
        """
        self._send(self.CMD_SET_SOUND, bytes([self.SOUND_ON if enabled else self.SOUND_OFF]))

    def set_alarm(self, channel, mode=AlarmMode.Off, value1=None, value2=None):
        """Set alarm for channel.

        :param channel: 1..NUM_PROBES
        :param mode: ALARM_OFF, ALARM_TARGET, or ALARM_RANGE
        :param value1: target temp (TARGET) or high temp (RANGE)
        :param value2: low temp (RANGE only)
        """
        channel = self._validate_channel(channel)
        if mode == AlarmMode.Off:
            t1 = b'\xff\xff'
            t2 = b'\xff\xff'
            encodedMode = self.ALARM_OFF
        elif mode == AlarmMode.Target:
            t1 = _encode_temp_bcd(value1)
            t2 = b'\x00\x00'
            encodedMode = self.ALARM_TARGET
        elif mode == AlarmMode.Range:
            t1 = _encode_temp_bcd(value1)
            t2 = _encode_temp_bcd(value2)
            encodedMode = self.ALARM_RANGE
        else:
            t1 = b'\xff\xff'
            t2 = b'\xff\xff'
            encodedMode = self.ALARM_OFF
        self._send(self.CMD_SET_ALARM, bytes([channel, encodedMode]) + t1 + t2)

    def sync_time(self, epoch_2020=None):
        """Sync device time.

        :param epoch_2020: seconds since 2020-01-01 UTC. If None, auto-calculated.
        """
        if epoch_2020 is None:
            try:
                from time import time
                epoch_2020 = int(time()) - self.EPOCH_2020
            except Exception:
                epoch_2020 = 0
        data = epoch_2020.to_bytes(4, 'little')
        self._send(self.CMD_TIME_SYNC, data)

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
        pkt = _build_packet(cmd, payload)
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
        if cmd == self.RX_TEMP_BROADCAST:
            if self._on_temperature:
                self._on_temperature(parsed)

        return (cmd, parsed)

    def _parse_packet(self, cmd, data):
        """Parse raw packet into appropriate data class."""
        pkt_len = data[1]

        broadcast_pkt_len = 3 + self.NUM_PROBES * 2
        actual_pkt_len = 2 + self.NUM_PROBES * 2

        if cmd == self.RX_TEMP_BROADCAST and pkt_len == broadcast_pkt_len and len(data) >= 2 + pkt_len:
            battery = data[2]
            units = _parse_units(data[3])
            alarms = data[4]
            temps = []
            for i in range(self.NUM_PROBES):
                offset = 5 + i * 2
                val = _decode_temp_bcd(data[offset:offset + 2])
                temps.append(Temperature(i + 1, val))
            return TemperatureBroadcast(battery, units, alarms, temps)

        if cmd == self.RX_TEMP_ACTUAL and pkt_len == actual_pkt_len and len(data) >= 2 + pkt_len:
            probe_count = data[2]
            alarms = data[3]
            temps = []
            for i in range(self.NUM_PROBES):
                offset = 4 + i * 2
                val = _decode_temp_bcd(data[offset:offset + 2])
                temps.append(Temperature(i + 1, val))
            return TemperatureActual(probe_count, alarms, temps)

        if cmd == self.RX_ALARM and pkt_len == 0x06 and len(data) >= 8:
            channel = data[2]
            if channel < 1 or channel > self.NUM_PROBES:
                return bytes(data[2:2 + pkt_len])
            mode = data[3]
            val1 = _decode_temp_bcd(data[4:6])
            val2 = _decode_temp_bcd(data[6:8])
            return AlarmConfig(channel, mode, val1, val2)

        if cmd == self.RX_FW_VERSION and pkt_len == 0x03 and len(data) >= 5:
            v = data[2:5]
            major = v[0] >> 4
            minor = v[0] & 0x0F
            patch = v[1]
            build = v[2]
            return FirmwareVersion(major, minor, patch, build)

        if cmd == self.RX_STATUS and pkt_len == 0x05 and len(data) >= 7:
            units = _parse_units(data[2])
            beeper = data[3] == 0x0C  # 0x0c=ON, 0x0f=OFF
            battery = data[4]
            return DeviceStatus(units, beeper, battery)

        if cmd == self.RX_AUTH and pkt_len == 0x02 and len(data) >= 4:
            return AuthResponse(bytes(data[2:4]))

        # Unknown or unparsed - return raw data bytes
        return bytes(data[2:2 + pkt_len])
