from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import DOMAIN
from .device import TP90xEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    device = hass.data[DOMAIN][entry.entry_id]
    entities = [TP90xAlarmSoundSwitch(device)]
    if device.supports_alarm_config:
        entities.extend([
            TP90xProbeAlarmSwitch(device, 1),
            TP90xProbeAlarmSwitch(device, 2),
        ])
    async_add_entities(entities)


class TP90xAlarmSoundSwitch(TP90xEntity, SwitchEntity):
    _attr_icon = "mdi:volume-high"
    _attr_name = "Alarm sound"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device) -> None:
        super().__init__(device, "alarm_sound", "Alarm sound")

    @property
    def is_on(self) -> bool | None:
        return self.device.beeper

    async def async_turn_on(self, **kwargs) -> None:
        await self.device.async_set_sound_alarm(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.device.async_set_sound_alarm(False)


class TP90xProbeAlarmSwitch(TP90xEntity, SwitchEntity):
    _attr_icon = "mdi:bell-ring-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device, channel: int) -> None:
        super().__init__(device, f"probe_{channel}_alarm", f"Probe {channel} alarm")
        self.channel = channel

    @property
    def is_on(self) -> bool:
        cfg = self.device.alarm_configs.get(self.channel, {})
        return cfg.get("mode") == 0x82

    async def async_turn_on(self, **kwargs) -> None:
        await self.device.async_enable_alarm(self.channel)

    async def async_turn_off(self, **kwargs) -> None:
        await self.device.async_set_alarm_off(self.channel)
