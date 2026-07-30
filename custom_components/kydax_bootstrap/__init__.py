"""Kydax Bootstrap: provisions a fresh Home Assistant box for a venue."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import KydaxBootstrapHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]

type KydaxBootstrapConfigEntry = ConfigEntry[KydaxBootstrapHub]


async def async_setup_entry(
    hass: HomeAssistant, entry: KydaxBootstrapConfigEntry
) -> bool:
    hub = KydaxBootstrapHub(hass, entry)
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hub.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: KydaxBootstrapConfigEntry
) -> bool:
    entry.runtime_data.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: KydaxBootstrapConfigEntry
) -> None:
    hub = entry.runtime_data
    significant = hub._significant_options(entry.options)
    if significant == hub.significant:
        # only provisioning progress moved: the running machine wrote it,
        # reloading now would kill the machine mid-run
        return
    await hass.config_entries.async_reload(entry.entry_id)
