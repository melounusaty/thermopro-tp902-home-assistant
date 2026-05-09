from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .device import TP90xEntity


def _c_to_f(value: float) -> float:
    return (value * 9.0 / 5.0) + 32.0


def _f_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    if not device.supports_alarm_config:
        return
    async_add_entities(
        [
            TP90xAlarmNumber(device, 1, "min"),
            TP90xAlarmNumber(device, 1, "max"),
            TP90xAlarmNumber(device, 2, "min"),
            TP90xAlarmNumber(device, 2, "max"),
        ]
    )


class TP90xAlarmNumber(TP90xEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_step = 0.1
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device, channel: int, kind: str) -> None:
        label = "Min" if kind == "min" else "Max"
        super().__init__(device, f"probe_{channel}_{kind}", f"Probe {channel} {label}")
        self.channel = channel
        self.kind = kind

    @property
    def native_unit_of_measurement(self):
        if self.device.display_units == "F":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def native_min_value(self):
        return -999.9 if self.device.display_units != "F" else round(_c_to_f(-999.9), 1)

    @property
    def native_max_value(self):
        return 999.9 if self.device.display_units != "F" else round(_c_to_f(999.9), 1)

    @property
    def native_value(self):
        cfg = self.device.alarm_configs.get(self.channel, {})
        value_c = cfg.get(self.kind)
        if value_c is None:
            value_c = self.device.alarm_memory.get(self.channel, {}).get(self.kind)
        if value_c is None:
            return None
        if self.device.display_units == "F":
            return round(_c_to_f(float(value_c)), 1)
        return round(float(value_c), 1)

    async def async_set_native_value(self, value: float) -> None:
        cfg = self.device.alarm_configs.get(self.channel, {})
        min_c = cfg.get("min")
        max_c = cfg.get("max")

        if min_c is None:
            min_c = self.device.alarm_memory.get(self.channel, {}).get("min")
        if max_c is None:
            max_c = self.device.alarm_memory.get(self.channel, {}).get("max")

        new_value_c = _f_to_c(value) if self.device.display_units == "F" else value
        new_value_c = round(float(new_value_c), 1)

        if self.kind == "min":
            min_c = new_value_c
        else:
            max_c = new_value_c

        if min_c is None and max_c is not None:
            min_c = max_c
        if max_c is None and min_c is not None:
            max_c = min_c
        if min_c is None or max_c is None:
            current = self.device.probes[self.channel - 1]
            if current is None:
                min_c = 0.0 if min_c is None else min_c
                max_c = 100.0 if max_c is None else max_c
            else:
                min_c = round(current - 5.0, 1) if min_c is None else min_c
                max_c = round(current + 5.0, 1) if max_c is None else max_c

        if float(min_c) > float(max_c):
            if self.kind == "min":
                max_c = min_c
            else:
                min_c = max_c

        await self.device.async_set_alarm_range(self.channel, float(min_c), float(max_c))
