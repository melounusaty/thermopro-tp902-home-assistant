from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .tp90x import AlarmMode, TP902, TP904
from .tp90x.tp90xbase import _build_packet, _encode_temp_bcd

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tp90x_multi"
TP90X_SERVICE_UUID = TP902.SERVICE_UUID
MODEL_MAP = {
    "TP902": TP902,
    "TP904": TP904,
}


class TP90xDevice:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.mac: str = entry.data["mac"]
        self.name: str = entry.data["name"]
        self.model: str = entry.data.get("model", "TP902")
        self.experimental: bool = self.model == "TP904"

        self.protocol_cls = MODEL_MAP.get(self.model, TP902)
        self.parser = self.protocol_cls(None)
        self.num_probes = self.protocol_cls.NUM_PROBES

        self.available = False
        self.rssi: int | None = None
        self.probes: list[float | None] = [None] * self.num_probes
        self.battery: int | None = None
        self.display_units: str | None = None
        self.alarms: int | None = None
        self.beeper: bool | None = None

        self.supports_alarm_config = self.model == "TP902"
        self.alarm_probe_count = 2 if self.supports_alarm_config else 0
        self.alarm_configs: dict[int, dict[str, float | int | None]] = {
            i: {"mode": None, "min": None, "max": None}
            for i in range(1, self.alarm_probe_count + 1)
        }
        self.alarm_memory: dict[int, dict[str, float | None]] = {
            i: {"min": None, "max": None}
            for i in range(1, self.alarm_probe_count + 1)
        }

        self.entities: list[Entity] = []
        self.task: asyncio.Task | None = None
        self._ble_device = None
        self._client: BleakClient | None = None
        self._command_lock = asyncio.Lock()

    def register(self, entity: Entity) -> None:
        self.entities.append(entity)

    def unregister(self, entity: Entity) -> None:
        if entity in self.entities:
            self.entities.remove(entity)

    def write_states(self) -> None:
        for entity in self.entities:
            entity.async_write_ha_state()

    async def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.mac.replace(":", "").lower())},
            connections={(CONNECTION_BLUETOOTH, self.mac)},
            manufacturer="ThermoPro",
            model=self.model,
            name=self.name,
        )

    @property
    def display_name(self) -> str:
        if self.experimental:
            return f"ThermoPro {self.model} (experimental)"
        return f"ThermoPro {self.model}"

    @property
    def integration_name(self) -> str:
        return "ThermoPro TP90X"

    @property
    def is_experimental(self) -> bool:
        return self.experimental

    @property
    def _device_info_passthrough(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.mac.replace(":", "").lower())},
            connections={(CONNECTION_BLUETOOTH, self.mac)},
            manufacturer="ThermoPro",
            model=self.model,
            name=self.name,
        )

    def handle_notify(self, _handle, data) -> None:
        try:
            raw = bytes(data)
            _LOGGER.debug("%s packet rx: %s", self.model, raw.hex())
            cmd, obj = self.parser._handle_raw(raw)

            if cmd == self.parser.RX_TEMP_BROADCAST and obj:
                temps = getattr(obj, "temperatures", []) or []
                probe_values: list[float | None] = []
                for i in range(self.num_probes):
                    if i < len(temps):
                        probe_values.append(getattr(temps[i], "value", None))
                    else:
                        probe_values.append(None)

                self.probes = probe_values
                self.battery = getattr(obj, "battery", self.battery)
                self.alarms = getattr(obj, "alarms", self.alarms)
                self.available = True
                self.hass.loop.call_soon_threadsafe(self.write_states)

            elif cmd == self.parser.RX_STATUS and obj:
                self.battery = getattr(obj, "battery", self.battery)
                self.display_units = getattr(obj, "units", self.display_units)
                self.beeper = getattr(obj, "beeper", self.beeper)
                self.available = True
                self.hass.loop.call_soon_threadsafe(self.write_states)

            elif self.supports_alarm_config and cmd == self.parser.RX_ALARM and obj:
                channel = getattr(obj, "channel", None)
                if channel in self.alarm_configs:
                    mode = getattr(obj, "mode", None)
                    low = getattr(obj, "value2", None)
                    high = getattr(obj, "value1", None)
                    self.alarm_configs[channel] = {
                        "mode": mode,
                        "min": low,
                        "max": high,
                    }
                    if low is not None:
                        self.alarm_memory[channel]["min"] = low
                    if high is not None:
                        self.alarm_memory[channel]["max"] = high
                    self.available = True
                    self.hass.loop.call_soon_threadsafe(self.write_states)

        except Exception as err:
            _LOGGER.exception("%s notify parse failed: %r", self.model, err)

    def _find_ble_device(self):
        for service_info in bluetooth.async_discovered_service_info(self.hass):
            address = getattr(service_info, "address", None)
            service_uuids = [
                s.lower() for s in getattr(service_info, "service_uuids", []) or []
            ]

            if (
                address
                and address.lower() == self.mac.lower()
                and TP90X_SERVICE_UUID in service_uuids
            ):
                return service_info.device

            if address and address.lower() == self.mac.lower():
                return service_info.device

        return self._ble_device

    async def async_send_packet(self, cmd: int, payload: bytes = b"") -> None:
        async with self._command_lock:
            if self._client is None or not self._client.is_connected:
                raise HomeAssistantError(f"{self.model} is not connected")

            await self._client.write_gatt_char(
                self.protocol_cls.WRITE_UUID,
                _build_packet(cmd, payload),
                response=True,
            )

    async def async_request_status(self) -> None:
        await self.async_send_packet(self.protocol_cls.CMD_GET_STATUS)

    async def async_get_alarm(self, channel: int) -> None:
        if not self.supports_alarm_config:
            return
        await self.async_send_packet(self.protocol_cls.CMD_GET_ALARM, bytes([channel]))

    async def async_set_units(self, celsius: bool) -> None:
        await self.async_send_packet(
            self.protocol_cls.CMD_SET_UNITS,
            bytes([self.protocol_cls.UNITS_C if celsius else self.protocol_cls.UNITS_F]),
        )
        await asyncio.sleep(0.8)
        await self.async_request_status()

    async def async_set_sound_alarm(self, enabled: bool) -> None:
        await self.async_send_packet(
            self.protocol_cls.CMD_SET_SOUND,
            bytes([self.protocol_cls.SOUND_ON if enabled else self.protocol_cls.SOUND_OFF]),
        )
        await asyncio.sleep(0.5)
        await self.async_request_status()

    async def async_alarm_snooze(self) -> None:
        await self.async_send_packet(self.protocol_cls.CMD_SNOOZE_ALARM)

    async def async_backlight(self) -> None:
        await self.async_send_packet(self.protocol_cls.CMD_BACKLIGHT_ON)


    async def async_set_alarm_range(self, channel: int, low_c: float, high_c: float) -> None:
        if not self.supports_alarm_config:
            raise HomeAssistantError(f"{self.model} alarm configuration is not supported")
        if channel not in self.alarm_configs:
            raise HomeAssistantError("Unsupported probe channel")
        if low_c > high_c:
            low_c, high_c = high_c, low_c

        payload = bytes([channel, self.protocol_cls.ALARM_RANGE]) + _encode_temp_bcd(high_c) + _encode_temp_bcd(low_c)
        await self.async_send_packet(self.protocol_cls.CMD_SET_ALARM, payload)
        self.alarm_memory[channel]["min"] = low_c
        self.alarm_memory[channel]["max"] = high_c
        await asyncio.sleep(0.5)
        await self.async_get_alarm(channel)

    async def async_set_alarm_off(self, channel: int) -> None:
        if not self.supports_alarm_config:
            raise HomeAssistantError(f"{self.model} alarm configuration is not supported")
        if channel not in self.alarm_configs:
            raise HomeAssistantError("Unsupported probe channel")
        payload = bytes([channel, self.protocol_cls.ALARM_OFF]) + b"\xff\xff\xff\xff"
        await self.async_send_packet(self.protocol_cls.CMD_SET_ALARM, payload)
        await asyncio.sleep(0.5)
        await self.async_get_alarm(channel)

    async def async_enable_alarm(self, channel: int) -> None:
        if not self.supports_alarm_config:
            raise HomeAssistantError(f"{self.model} alarm configuration is not supported")
        if channel not in self.alarm_configs:
            raise HomeAssistantError("Unsupported probe channel")

        low_c = self.alarm_memory[channel]["min"]
        high_c = self.alarm_memory[channel]["max"]

        if low_c is None or high_c is None:
            current = self.probes[channel - 1] if channel - 1 < len(self.probes) else None
            if current is not None:
                low_c = round(current - 5.0, 1)
                high_c = round(current + 5.0, 1)
            else:
                low_c = 0.0
                high_c = 100.0

        await self.async_set_alarm_range(channel, float(low_c), float(high_c))

    async def async_refresh_all(self) -> None:
        await self.async_request_status()
        if self.supports_alarm_config:
            for channel in sorted(self.alarm_configs):
                await asyncio.sleep(0.2)
                await self.async_get_alarm(channel)

    async def _run(self) -> None:
        while True:
            client = None
            try:
                ble_device = self._find_ble_device()

                if ble_device is None:
                    _LOGGER.debug(
                        "%s not currently visible via HA Bluetooth: %s",
                        self.model,
                        self.mac,
                    )
                    await asyncio.sleep(15)
                    continue

                self._ble_device = ble_device
                self.rssi = getattr(ble_device, "rssi", None)

                _LOGGER.debug(
                    "%s connecting to %s (rssi=%s)",
                    self.model,
                    self.mac,
                    self.rssi,
                )

                client = await establish_connection(BleakClient, ble_device, self.name)
                self._client = client
                _LOGGER.debug("%s connected", self.model)

                await client.start_notify(self.protocol_cls.NOTIFY_UUID, self.handle_notify)
                _LOGGER.debug("%s notify started", self.model)
                await asyncio.sleep(0.5)

                await client.write_gatt_char(self.protocol_cls.WRITE_UUID, self.protocol_cls.AUTH_PACKET, response=True)
                _LOGGER.debug("%s auth sent", self.model)
                await asyncio.sleep(1.0)

                await self.async_refresh_all()
                _LOGGER.debug("%s initial refresh sent", self.model)

                self.available = True
                self.write_states()

                while True:
                    await asyncio.sleep(30)
                    await self.async_refresh_all()
                    _LOGGER.debug("%s periodic refresh sent", self.model)

            except asyncio.CancelledError:
                raise
            except BleakError as err:
                _LOGGER.debug("%s BLE connect/retry failed: %r", self.model, err)
                self.available = False
                self.write_states()
                await asyncio.sleep(10)
            except Exception as err:
                _LOGGER.exception("%s disconnected / retrying, exception=%r", self.model, err)
                self.available = False
                self.write_states()
                await asyncio.sleep(10)
            finally:
                self._client = None
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass


class TP90xEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: TP90xDevice, key: str, name: str) -> None:
        self.device = device
        self._attr_name = name
        self._attr_unique_id = f"{device.mac.replace(':', '').lower()}_{key}"

    async def async_added_to_hass(self) -> None:
        self.device.register(self)
        await self.device.start()

    async def async_will_remove_from_hass(self) -> None:
        self.device.unregister(self)
        if not self.device.entities:
            await self.device.stop()

    @property
    def available(self) -> bool:
        return self.device.available

    @property
    def device_info(self) -> DeviceInfo:
        return self.device.device_info

    @property
    def extra_state_attributes(self):
        return {
            "integration_name": self.device.integration_name,
            "device_model": self.device.model,
            "experimental_support": self.device.is_experimental,
            "device_display_units": self.device.display_units,
            "alarms": self.device.alarms,
            "beeper": self.device.beeper,
            "rssi": self.device.rssi,
        }
