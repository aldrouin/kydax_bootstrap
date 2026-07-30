"""The venue bundle: one JSON document describing everything to provision.

Shape (version 1) — the kydax_sound / kydax_light sections are exactly the
portable payloads those integrations export, plus the site keys the exports
deliberately leave out (host, source entities):

{
  "kydax_bundle": {
    "bundle_version": 1,
    "venue": {"name": "..."},
    "components": [
      {"repo": "aldrouin/kydax_sound", "type": "integration",
       "domain": "kydax_sound", "version": "latest"},
      {"repo": "NemesisRE/kiosk-mode", "type": "plugin",
       "asset": "kiosk-mode.js", "version": "latest"}
    ],
    "kydax_sound": {"host": "...", ...portable keys...},
    "kydax_light": {"source_mode": "lux", "lux_entity": "...", ...},
    "dashboard": {
      "url_path": "restaurant", "title": "...", "icon": "mdi:...",
      "background_image": "/local/kydax/background.jpg",
      "kiosk": {"non_admin_settings": {"hide_header": true,
                                       "hide_sidebar": true}},
      "views": [{"title": "...", "icon": "mdi:...", "cards": [
        {"type": "entities", "entities": ["$sound:level_50", "$light:pause_ab12"]}
      ]}]
    },
    "auto_update": {"critical_always": true}
  }
}

Card entities may use placeholders "$sound:<unique-suffix>" and
"$light:<unique-suffix>" resolved through the entity registry at build
time, because entity_ids are not predictable across installs.
"""

from __future__ import annotations

import copy
from typing import Any

BUNDLE_KEY = "kydax_bundle"
BUNDLE_VERSION = 1

SIBLING_DOMAINS = ("kydax_sound", "kydax_light")

DEFAULT_BUNDLE: dict[str, Any] = {
    "bundle_version": BUNDLE_VERSION,
    "venue": {"name": ""},
    "components": [
        {
            "repo": "aldrouin/kydax_sound",
            "type": "integration",
            "domain": "kydax_sound",
            "version": "latest",
        },
        {
            "repo": "aldrouin/kydax_light",
            "type": "integration",
            "domain": "kydax_light",
            "version": "latest",
        },
        {
            "repo": "aldrouin/kydax_test",
            "type": "integration",
            "domain": "kydax_test",
            "version": "latest",
        },
        {
            "repo": "aldrouin/kydax_bootstrap",
            "type": "integration",
            "domain": "kydax_bootstrap",
            "version": "latest",
        },
        {
            "repo": "NemesisRE/kiosk-mode",
            "type": "plugin",
            "asset": "kiosk-mode.js",
            "version": "latest",
        },
    ],
    "kydax_sound": {},
    "kydax_light": {},
    "dashboard": {
        "url_path": "restaurant",
        "title": "Restaurant",
        "icon": "mdi:silverware-fork-knife",
        "background_image": "",
        "kiosk": {
            "non_admin_settings": {"hide_header": True, "hide_sidebar": True}
        },
        "views": [],
    },
    "auto_update": {"critical_always": True},
}


def default_bundle() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_BUNDLE)


def strip_comments(value: Any) -> Any:
    """Drop the annotations added on export (keys starting with _)."""
    if isinstance(value, dict):
        return {
            key: strip_comments(item)
            for key, item in value.items()
            if not key.startswith("_")
        }
    if isinstance(value, list):
        return [strip_comments(item) for item in value]
    return value


def normalize(data: Any) -> dict[str, Any] | None:
    """Accept a whole export file or a bare bundle; None when unusable."""
    if not isinstance(data, dict):
        return None
    bundle = strip_comments(data.get(BUNDLE_KEY, data))
    if not isinstance(bundle, dict):
        return None
    # merge over the defaults so partial bundles stay complete
    merged = default_bundle()
    for key, value in bundle.items():
        if key == "dashboard" and isinstance(value, dict):
            merged["dashboard"].update(value)
        else:
            merged[key] = value
    return merged


def validate(bundle: Any) -> str | None:
    """Return an error key when the bundle is unusable."""
    if not isinstance(bundle, dict):
        return "invalid_file"
    if bundle.get("bundle_version") != BUNDLE_VERSION:
        return "invalid_version"
    components = bundle.get("components")
    if not isinstance(components, list):
        return "invalid_components"
    for component in components:
        if (
            not isinstance(component, dict)
            or "/" not in str(component.get("repo", ""))
            or component.get("type") not in ("integration", "plugin")
            or (component["type"] == "integration" and not component.get("domain"))
            or (component["type"] == "plugin" and not component.get("asset"))
        ):
            return "invalid_components"
    dashboard = bundle.get("dashboard")
    if dashboard is not None and (
        not isinstance(dashboard, dict)
        or not isinstance(dashboard.get("views", []), list)
    ):
        return "invalid_dashboard"
    for domain in SIBLING_DOMAINS:
        section = bundle.get(domain)
        if section is not None and not isinstance(section, dict):
            return "invalid_file"
    return None


def export_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """The bundle wrapped for download, with a short how-to comment."""
    return {
        "_comment": (
            "Kydax venue bundle. Import it in Kydax Bootstrap on a fresh box "
            "to install and configure everything. Keys starting with _ are "
            "ignored."
        ),
        BUNDLE_KEY: bundle,
    }


def integration_components(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in bundle.get("components", []) if c.get("type") == "integration"]


def plugin_components(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in bundle.get("components", []) if c.get("type") == "plugin"]
