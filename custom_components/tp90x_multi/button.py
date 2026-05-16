from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .device import TP90xEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    device = hass.data[DOMAIN][entry.entry_id]

    entities = [
        TP90xAlarmSnoozeButton(device),
        TP90xBacklightButton(device),
    ]

    async_add_entities(entities)


class TP90xAlarmSnoozeButton(TP90xEntity, ButtonEntity):
    _attr_icon = "mdi:bell-sleep-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device) -> None:
        super().__init__(device, "alarm_snooze", "Alarm snooze")

    async def async_press(self) -> None:
        await self.device.async_alarm_snooze()


class TP90xBacklightButton(TP90xEntity, ButtonEntity):
    _attr_icon = "mdi:lightbulb-on-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device) -> None:
        super().__init__(device, "backlight", "Backlight")

    async def async_press(self) -> None:
        await self.device.async_backlight()
