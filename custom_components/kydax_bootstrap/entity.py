"""Base entity for Kydax Bootstrap."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, signal_update
from .coordinator import KydaxBootstrapHub


class KydaxBootstrapEntity(Entity):
    """Entity attached to the Kydax Bootstrap hub device, push-updated."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        self._hub = hub
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.entry.entry_id)},
            name="Kydax Bootstrap",
            manufacturer="Kydax",
            model="Provisioning",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update(self._hub.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
