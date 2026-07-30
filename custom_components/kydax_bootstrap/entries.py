"""Create or update the sibling integrations' config entries from the bundle."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .bundle import SIBLING_DOMAINS

_LOGGER = logging.getLogger(__name__)

# keys the bundle carries but the sibling options must not blindly receive
_PORTABLE_ONLY = {"kydax_sound": (), "kydax_light": ()}


class EntryError(Exception):
    """A sibling entry could not be created or updated."""


def existing_entry(hass: HomeAssistant, domain: str) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(domain)
    return entries[0] if entries else None


async def async_apply_section(
    hass: HomeAssistant, domain: str, section: dict[str, Any]
) -> str:
    """Create the sibling entry from its bundle section, or merge into it.

    Returns "created", "updated" or "skipped" (empty section).
    """
    if domain not in SIBLING_DOMAINS:
        raise EntryError(f"unknown sibling domain {domain}")
    if not section:
        return "skipped"

    entry = existing_entry(hass, domain)
    if entry is None:
        result = await hass.config_entries.flow.async_init(
            domain, context={"source": SOURCE_IMPORT}, data=section
        )
        if result.get("type") is not FlowResultType.CREATE_ENTRY:
            raise EntryError(
                f"{domain} import rejected: {result.get('reason', result.get('type'))}"
            )
        _LOGGER.info("Created %s entry from the bundle", domain)
        return "created"

    # merge: the bundle wins for every key it carries, the rest is kept
    options = {**entry.options, **section}
    if options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=options)
        _LOGGER.info("Updated %s options from the bundle", domain)
        return "updated"
    return "skipped"


async def async_wait_loaded(
    hass: HomeAssistant, domain: str, timeout: float = 60.0
) -> bool:
    """Wait for the sibling's entry to reach LOADED (it reloads on update)."""
    deadline = hass.loop.time() + timeout
    while hass.loop.time() < deadline:
        entry = existing_entry(hass, domain)
        if entry is not None and entry.state is ConfigEntryState.LOADED:
            return True
        if entry is not None and entry.state is ConfigEntryState.SETUP_ERROR:
            return False
        await asyncio.sleep(1)
    return False
