from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .device import TP90xEntity


def _c_to_f(value: float) -> float:
    return (value * 9.0 / 5.0) + 32.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    probe_count = 2 if device.model == "TP902" else device.num_probes
    entities = [TP90xProbeSensor(device, idx, f"Probe {idx + 1}") for idx in range(probe_count)]
    entities.append(TP90xBatterySensor(device))
    async_add_entities(entities)


class TP90xProbeSensor(TP90xEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, device, index: int, name: str) -> None:
        super().__init__(device, f"probe_{index + 1}", name)
        self.index = index

    @property
    def native_value(self):
        if self.index >= len(self.device.probes):
            return None
        value = self.device.probes[self.index]
        if value is None:
            return None
        if self.device.display_units == "F":
            return round(_c_to_f(value), 1)
        return round(value, 1)

    @property
    def native_unit_of_measurement(self):
        if self.device.display_units == "F":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def extra_state_attributes(self):
        attrs = dict(super().extra_state_attributes or {})
        if self.device.supports_alarm_config:
            cfg = self.device.alarm_configs.get(self.index + 1, {})
            if cfg:
                attrs["alarm_enabled"] = cfg.get("mode") == 0x82
                attrs["alarm_min_c"] = cfg.get("min")
                attrs["alarm_max_c"] = cfg.get("max")
        return attrs


class TP90xBatterySensor(TP90xEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, device) -> None:
        super().__init__(device, "battery", "Battery")

    @property
    def native_value(self):
        return self.device.battery
