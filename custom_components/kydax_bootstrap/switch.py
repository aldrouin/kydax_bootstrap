"""Opt-in switch for the centralized nightly auto-update."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import KydaxBootstrapHub
from .entity import KydaxBootstrapEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: KydaxBootstrapHub = entry.runtime_data
    async_add_entities([KydaxBootstrapAutoUpdateSwitch(hub)])


class KydaxBootstrapAutoUpdateSwitch(
    KydaxBootstrapEntity, SwitchEntity, RestoreEntity
):
    """Default off; releases marked [critical] install regardless."""

    _attr_translation_key = "auto_update"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:update"

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_auto_update"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == STATE_ON
        self._hub.auto_update_enabled = bool(self._attr_is_on)

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self._hub.auto_update_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self._hub.auto_update_enabled = False
        self.async_write_ha_state()
