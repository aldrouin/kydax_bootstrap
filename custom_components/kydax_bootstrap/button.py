"""Action buttons: resume provisioning, check updates, rebuild dashboard."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PHASE_DASHBOARD, PHASE_HOLD, PHASE_PENDING
from .coordinator import KydaxBootstrapHub
from .entity import KydaxBootstrapEntity


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: KydaxBootstrapHub = entry.runtime_data
    async_add_entities(
        [
            KydaxBootstrapResumeButton(hub),
            KydaxBootstrapCheckUpdatesButton(hub),
            KydaxBootstrapRebuildDashboardButton(hub),
        ]
    )


class _BaseButton(KydaxBootstrapEntity, ButtonEntity):
    def _background(self, coro, name: str) -> None:
        self._hub.entry.async_create_background_task(self.hass, coro, name)


class KydaxBootstrapResumeButton(_BaseButton):
    """Start (or retry) provisioning from the current phase."""

    _attr_translation_key = "resume"
    _attr_icon = "mdi:play-circle"

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_resume"

    async def async_press(self) -> None:
        if self._hub.phase == PHASE_HOLD:
            self._hub.set_phase(PHASE_PENDING)
        self._background(self._hub.async_resume(), "kydax_bootstrap_resume")


class KydaxBootstrapCheckUpdatesButton(_BaseButton):
    """Refresh the per-component update status shown on the status sensor."""

    _attr_translation_key = "check_updates"
    _attr_icon = "mdi:cloud-search"

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_check_updates"

    async def async_press(self) -> None:
        self._background(self._hub.async_check_updates(), "kydax_bootstrap_check")


class KydaxBootstrapRebuildDashboardButton(_BaseButton):
    """Regenerate the customer dashboard from the bundle."""

    _attr_translation_key = "rebuild_dashboard"
    _attr_icon = "mdi:view-dashboard-edit"

    def __init__(self, hub: KydaxBootstrapHub) -> None:
        super().__init__(hub)
        self._attr_unique_id = f"{hub.entry.entry_id}_rebuild_dashboard"

    async def async_press(self) -> None:
        self._hub.set_phase(PHASE_DASHBOARD)
        self._background(self._hub.async_resume(), "kydax_bootstrap_rebuild")
