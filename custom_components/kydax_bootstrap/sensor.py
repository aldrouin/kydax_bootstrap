"""Provisioning status sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KydaxBootstrapHub
from .entity import KydaxBootstrapEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: KydaxBootstrapHub = entry.runtime_data
    async_add_entities([KydaxBootstrapStatusSensor(hub)])


class KydaxBootstrapStatusSensor(KydaxBootstrapEntity, SensorEntity):
    """The current provisioning phase, with everything else as attributes."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:progress-wrench"

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        return self._hub.phase

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "error": self._hub.last_error or self._hub.provisioning.get("error"),
            "installed": self._hub.provisioning.get("installed", {}),
            "updates": self._hub.update_info,
            "dropped_placeholders": self._hub.dropped_placeholders,
            "venue": (self._hub.bundle.get("venue") or {}).get("name"),
        }
