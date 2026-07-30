"""Build the customer-facing Lovelace dashboard from the bundle.

This is the one module that touches Lovelace internals (the thin layer
directly under the stable websocket commands). Every access is guarded:
failure means "create the dashboard manually", never a broken venue.

Note: hass.data[LOVELACE_DATA] holds the live dashboards/resources, but the
DashboardsCollection that registers *new* dashboards lives only inside the
lovelace setup closure — so a brand-new dashboard is persisted through our
own collection instance over the same store and its sidebar panel appears
after the next restart (provisioning restarts anyway).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .bundle import SIBLING_DOMAINS

_LOGGER = logging.getLogger(__name__)

_PLACEHOLDER_PREFIXES = {"$sound:": "kydax_sound", "$light:": "kydax_light"}


class DashboardError(Exception):
    """The dashboard could not be created or saved."""


def _entity_map(hass: HomeAssistant) -> dict[str, str]:
    """{"$sound:<suffix>": entity_id, "$light:<suffix>": entity_id, ...}"""
    registry = er.async_get(hass)
    mapping: dict[str, str] = {}
    prefix_by_domain = {domain: p for p, domain in _PLACEHOLDER_PREFIXES.items()}
    for domain in SIBLING_DOMAINS:
        for entry in hass.config_entries.async_entries(domain):
            for reg_entry in er.async_entries_for_config_entry(
                registry, entry.entry_id
            ):
                suffix = reg_entry.unique_id.removeprefix(f"{entry.entry_id}_")
                mapping[prefix_by_domain[domain] + suffix] = reg_entry.entity_id
    return mapping


def _resolve(value: Any, mapping: dict[str, str], dropped: list[str]) -> Any:
    """Replace placeholders everywhere in the view structure.

    Unresolvable placeholders are collected and removed from entity lists
    (a card with a dead reference would error in the UI).
    """
    if isinstance(value, str):
        if any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES):
            resolved = mapping.get(value)
            if resolved is None:
                dropped.append(value)
                return None
            return resolved
        return value
    if isinstance(value, list):
        resolved_list = [_resolve(item, mapping, dropped) for item in value]
        return [item for item in resolved_list if item is not None]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            resolved = _resolve(item, mapping, dropped)
            if resolved is None and isinstance(item, str):
                continue  # e.g. a card's single "entity" that vanished
            out[key] = resolved
        return out
    return value


def build_config(hass: HomeAssistant, dashboard: dict[str, Any]) -> tuple[dict, list]:
    """The full Lovelace config for the bundle's dashboard section."""
    mapping = _entity_map(hass)
    dropped: list[str] = []
    views = []
    background = dashboard.get("background_image") or ""
    for view in dashboard.get("views", []):
        resolved = _resolve(view, mapping, dropped)
        if background and "background" not in resolved:
            resolved["background"] = {
                "image": background,
                "size": "cover",
                "alignment": "center",
                "repeat": "no-repeat",
                "attachment": "fixed",
                "opacity": 100,
            }
        views.append(resolved)
    config: dict[str, Any] = {"views": views}
    kiosk = dashboard.get("kiosk")
    if kiosk:
        # the kiosk-mode plugin reads its settings from the dashboard config
        config["kiosk_mode"] = kiosk
    if dropped:
        _LOGGER.warning(
            "Dashboard placeholders without a matching entity were dropped: %s",
            ", ".join(sorted(set(dropped))),
        )
    return config, sorted(set(dropped))


async def async_build(
    hass: HomeAssistant, dashboard: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Create/refresh the dashboard. Returns (created_new, dropped).

    created_new means a restart is needed for the sidebar panel to appear.
    """
    url_path = dashboard.get("url_path") or "restaurant"
    title = dashboard.get("title") or "Restaurant"
    config, dropped = build_config(hass, dashboard)

    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace import dashboard as lv_dashboard

        lovelace = hass.data[LOVELACE_DATA]
        created_new = False

        if url_path not in lovelace.dashboards:
            collection = lv_dashboard.DashboardsCollection(hass)
            await collection.async_load()
            item = next(
                (
                    existing
                    for existing in collection.async_items()
                    if existing.get("url_path") == url_path
                ),
                None,
            )
            if item is None:
                item = await collection.async_create_item(
                    {
                        "url_path": url_path,
                        "title": title,
                        "icon": dashboard.get("icon") or "mdi:silverware-fork-knife",
                        "show_in_sidebar": True,
                        "require_admin": False,
                    }
                )
                created_new = True
            storage = lv_dashboard.LovelaceStorage(hass, item)
        else:
            storage = lovelace.dashboards[url_path]

        await storage.async_save(config)
        _LOGGER.info(
            "Dashboard /%s saved: %d view(s)%s",
            url_path,
            len(config["views"]),
            " (restart needed for the sidebar entry)" if created_new else "",
        )
        return created_new, dropped
    except DashboardError:
        raise
    except Exception as err:  # noqa: BLE001 — internal API; report, don't crash
        raise DashboardError(
            f"Lovelace internals rejected the dashboard: {err!r}"
        ) from err
