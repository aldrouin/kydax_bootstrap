"""Diagnostics: bundle (addresses redacted), provisioning state, updates."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BUNDLE
from .coordinator import KydaxBootstrapHub

TO_REDACT = {"host", "musiselect_host"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    hub: KydaxBootstrapHub = entry.runtime_data
    return {
        "bundle": async_redact_data(
            entry.options.get(CONF_BUNDLE, {}), TO_REDACT
        ),
        "provisioning": hub.provisioning,
        "phase": hub.phase,
        "last_error": hub.last_error,
        "auto_update_enabled": hub.auto_update_enabled,
        "update_info": hub.update_info,
        "dropped_placeholders": hub.dropped_placeholders,
    }
