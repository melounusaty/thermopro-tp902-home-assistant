from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from . import DOMAIN
from .tp902_proto import (
    AUTH_PACKET,
    CMD_GET_STATUS,
    NOTIFY_UUID,
    RX_STATUS,
    RX_TEMP_BROADCAST,
    TP902,
    WRITE_UUID,
    build_packet,
)

_LOGGER = logging.getLogger(__name__)
TP902_SERVICE_UUID = "1086fff0-3343-4817-8bb2-b32206336ce8"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    device = TP902Device(hass, entry)
    entities = [
        TP902ProbeSensor(device, 0, "Probe 1"),
        TP902ProbeSensor(device, 1, "Probe 2"),
        TP902BatterySensor(device),
    ]
    async_add_entities(entities, True)


class TP902Device:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.mac: str = entry.data["mac"]
        self.name: str = entry.data["name"]
        self.parser = TP902(None)

        self.available = False
        self.rssi = None
        self.probes = [None, None, None, None, None, None]
        self.battery = None
        self.units = None
        self.alarms = None
        self.beeper = None

        self.entities: list[SensorEntity] = []
        self.task: asyncio.Task | None = None
        self._ble_device = None

    def register(self, entity: SensorEntity) -> None:
        self.entities.append(entity)

    def unregister(self, entity: SensorEntity) -> None:
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

    def handle_notify(self, _handle, data) -> None:
        try:
            raw = bytes(data)
            _LOGGER.debug("TP902 packet rx: %s", raw.hex())
            cmd, obj = self.parser._handle_raw(raw)

            if cmd == RX_TEMP_BROADCAST and obj:
                temps = getattr(obj, "temperatures", []) or []
                probe_values = []
                for i in range(6):
                    if i < len(temps):
                        probe_values.append(getattr(temps[i], "value", None))
                    else:
                        probe_values.append(None)

                self.probes = probe_values
                self.battery = getattr(obj, "battery", self.battery)
                self.units = getattr(obj, "units", self.units)
                self.alarms = getattr(obj, "alarms", self.alarms)
                self.available = True
                self.hass.loop.call_soon_threadsafe(self.write_states)

            elif cmd == RX_STATUS and obj:
                self.battery = getattr(obj, "battery", self.battery)
                self.units = getattr(obj, "units", self.units)
                self.beeper = getattr(obj, "beeper", self.beeper)
                self.available = True
                self.hass.loop.call_soon_threadsafe(self.write_states)

        except Exception as err:
            _LOGGER.exception("TP902 notify parse failed: %r", err)

    def _find_ble_device(self):
        for service_info in bluetooth.async_discovered_service_info(self.hass):
            address = getattr(service_info, "address", None)
            service_uuids = [
                s.lower() for s in getattr(service_info, "service_uuids", []) or []
            ]

            if (
                address
                and address.lower() == self.mac.lower()
                and TP902_SERVICE_UUID in service_uuids
            ):
                return service_info.device

            if address and address.lower() == self.mac.lower():
                return service_info.device

        return self._ble_device

    async def _run(self) -> None:
        while True:
            client = None
            try:
                ble_device = self._find_ble_device()

                if ble_device is None:
                    _LOGGER.debug(
                        "TP902 not currently visible via HA Bluetooth: %s",
                        self.mac,
                    )
                    await asyncio.sleep(15)
                    continue

                self._ble_device = ble_device
                self.rssi = getattr(ble_device, "rssi", None)
                _LOGGER.debug(
                    "TP902 connecting to %s (rssi=%s)",
                    self.mac,
                    self.rssi,
                )

                client = await establish_connection(
                    BleakClient,
                    ble_device,
                    self.name,
                )
                _LOGGER.debug("TP902 connected")

                await client.start_notify(NOTIFY_UUID, self.handle_notify)
                _LOGGER.debug("TP902 notify started")
                await asyncio.sleep(0.5)

                await client.write_gatt_char(WRITE_UUID, AUTH_PACKET, response=True)
                _LOGGER.debug("TP902 auth sent")
                await asyncio.sleep(1.0)

                await client.write_gatt_char(
                    WRITE_UUID,
                    build_packet(CMD_GET_STATUS),
                    response=True,
                )
                _LOGGER.debug("TP902 status request sent")

                self.available = True
                self.write_states()

                while True:
                    await asyncio.sleep(30)
                    await client.write_gatt_char(
                        WRITE_UUID,
                        build_packet(CMD_GET_STATUS),
                        response=True,
                    )
                    _LOGGER.debug("TP902 periodic status request sent")

            except asyncio.CancelledError:
                raise
            except BleakError as err:
                _LOGGER.debug("TP902 BLE connect/retry failed: %r", err)
                self.available = False
                self.write_states()
                await asyncio.sleep(10)
            except Exception as err:
                _LOGGER.exception("TP902 disconnected / retrying, exception=%r", err)
                self.available = False
                self.write_states()
                await asyncio.sleep(10)
            finally:
                if client is not None:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass


class TP902BaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: TP902Device, key: str, name: str) -> None:
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
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.mac.replace(":", "").lower())},
            connections={(CONNECTION_BLUETOOTH, self.device.mac)},
            manufacturer="ThermoPro",
            model="TP902",
            name=self.device.name,
        )

    @property
    def extra_state_attributes(self):
        return {
            "units": self.device.units,
            "alarms": self.device.alarms,
            "beeper": self.device.beeper,
            "rssi": self.device.rssi,
        }


class TP902ProbeSensor(TP902BaseSensor):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device: TP902Device, index: int, name: str) -> None:
        super().__init__(device, f"probe_{index + 1}", name)
        self.index = index

    @property
    def native_value(self):
        if self.index >= len(self.device.probes):
            return None
        return self.device.probes[self.index]


class TP902BatterySensor(TP902BaseSensor):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, device: TP902Device) -> None:
        super().__init__(device, "battery", "Battery")

    @property
    def native_value(self):
        return self.device.battery
