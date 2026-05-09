from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .device import TP90xEntity

OPTIONS = ["Celsius", "Fahrenheit"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TP90xUnitsSelect(device)])


class TP90xUnitsSelect(TP90xEntity, SelectEntity):
    _attr_options = OPTIONS
    _attr_icon = "mdi:thermometer"
    _attr_name = "Units"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device) -> None:
        super().__init__(device, "units", "Units")

    @property
    def current_option(self) -> str | None:
        if self.device.display_units == "C":
            return "Celsius"
        if self.device.display_units == "F":
            return "Fahrenheit"
        return None

    async def async_select_option(self, option: str) -> None:
        await self.device.async_set_units(option == "Celsius")
