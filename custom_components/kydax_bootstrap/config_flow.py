"""Config (wizard) and options flows for Kydax Bootstrap.

The initial flow is the venue wizard: start from an uploaded bundle (the
normal path — exported from a reference venue) or the built-in template,
overlay the site-specific values (Symetrix address, light source, local
light entities), optionally add customer switches and birthday events, set
up the customer dashboard, then create the entry and start provisioning.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    FileSelector,
    FileSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import bundle as bundle_lib
from .const import (
    CONF_BUNDLE,
    CONF_PROVISIONING,
    DOMAIN,
    PHASE_HOLD,
    PHASE_PENDING,
    WWW_SUBDIR,
)

_STATIC_URL = "/kydax_bootstrap_files"
_STATIC_REGISTERED = "kydax_bootstrap_static_registered"
DEFAULT_EXPORT_FILE = "kydax_bundle.json"


def _int_selector(minimum: int, maximum: int):
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(
                min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX
            )
        ),
        vol.Coerce(int),
    )


def _optional_int(minimum: int, maximum: int):
    return vol.Any(None, _int_selector(minimum, maximum))


def _detect_image_name(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "background.png"
    return "background.jpg"


async def _async_download_url(hass, directory: str, name: str) -> str:
    """Serve an export immediately, same pattern as the sibling flows."""
    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_URL, directory, False)]
        )
        hass.data[_STATIC_REGISTERED] = True
    return f"{_STATIC_URL}/{name}"


class KydaxBootstrapConfigFlow(ConfigFlow, domain=DOMAIN):
    """The venue wizard."""

    VERSION = 1

    def __init__(self) -> None:
        self._bundle: dict[str, Any] = bundle_lib.default_bundle()
        self._light_map: dict[str, str] = {}

    # --- step 1: venue + source --------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._bundle["venue"] = {"name": user_input["venue"].strip()}
            if user_input["source"] == "upload":
                return await self.async_step_bundle_file()
            return await self.async_step_site_sound()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("venue"): TextSelector(),
                    vol.Required("source", default="upload"): SelectSelector(
                        SelectSelectorConfig(
                            options=["upload", "template"],
                            translation_key="bundle_source",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_bundle_file(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:

            def _read() -> Any:
                with process_uploaded_file(self.hass, user_input["file"]) as path:
                    with open(path, encoding="utf-8") as handle:
                        return json.load(handle)

            try:
                data = await self.hass.async_add_executor_job(_read)
            except (OSError, ValueError, KeyError):
                errors["file"] = "invalid_file"
            else:
                venue = self._bundle["venue"]
                normalized = bundle_lib.normalize(data)
                problem = bundle_lib.validate(normalized) if normalized else "invalid_file"
                if normalized is None or problem:
                    errors["file"] = problem or "invalid_file"
                else:
                    self._bundle = normalized
                    if venue.get("name"):
                        self._bundle["venue"] = venue
                    return await self.async_step_site_sound()
        return self.async_show_form(
            step_id="bundle_file",
            data_schema=vol.Schema(
                {
                    vol.Required("file"): FileSelector(
                        FileSelectorConfig(accept=".json,application/json")
                    )
                }
            ),
            errors=errors,
        )

    # --- step 2: sound site values -----------------------------------------

    async def async_step_site_sound(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sound = dict(self._bundle.get("kydax_sound") or {})
        if user_input is not None:
            host = (user_input.get("host") or "").strip()
            if host:
                sound["host"] = host
                sound["port"] = user_input.get("port") or 48630
                musiselect = (user_input.get("musiselect_host") or "").strip()
                if musiselect:
                    sound["musiselect_host"] = musiselect
                else:
                    sound.pop("musiselect_host", None)
                self._bundle["kydax_sound"] = sound
            else:
                self._bundle["kydax_sound"] = {}
            return await self.async_step_site_light()
        return self.async_show_form(
            step_id="site_sound",
            data_schema=vol.Schema(
                {
                    vol.Optional("host", default=sound.get("host", "")): TextSelector(),
                    vol.Required(
                        "port", default=sound.get("port", 48630)
                    ): _int_selector(1, 65535),
                    vol.Optional(
                        "musiselect_host",
                        default=sound.get("musiselect_host", ""),
                    ): TextSelector(),
                }
            ),
        )

    # --- step 3: light site values -----------------------------------------

    async def async_step_site_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        light = dict(self._bundle.get("kydax_light") or {})
        errors: dict[str, str] = {}
        if user_input is not None:
            skip = user_input.get("skip_light", False)
            if skip:
                self._bundle["kydax_light"] = {}
                return await self.async_step_switches()
            mode = user_input["source_mode"]
            entity = user_input.get(
                "lux_entity" if mode == "lux" else "weather_entity"
            )
            if not entity:
                errors["base"] = "source_entity_required"
            else:
                light["source_mode"] = mode
                light.pop("lux_entity", None)
                light.pop("weather_entity", None)
                light["lux_entity" if mode == "lux" else "weather_entity"] = entity
                self._bundle["kydax_light"] = light
                if light.get("lights"):
                    return await self.async_step_light_map()
                return await self.async_step_light_pick()
        return self.async_show_form(
            step_id="site_light",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "source_mode", default=light.get("source_mode", "lux")
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["lux", "weather"],
                            translation_key="light_source_mode",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        "lux_entity",
                        description={
                            "suggested_value": light.get("lux_entity")
                        },
                    ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                    vol.Optional(
                        "weather_entity",
                        description={
                            "suggested_value": light.get("weather_entity")
                        },
                    ): EntitySelector(EntitySelectorConfig(domain="weather")),
                    vol.Required("skip_light", default=False): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_light_map(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Map every template light onto a local entity (unmapped = dropped)."""
        light = self._bundle.get("kydax_light") or {}
        template_lights = list((light.get("lights") or {}).keys())
        if user_input is not None:
            self._light_map = {
                old: new for old, new in user_input.items() if new and new != old
            }
            dropped = [
                old
                for old in template_lights
                if old not in user_input or not user_input.get(old)
            ]
            self._apply_light_map(dropped)
            return await self.async_step_switches()
        schema = vol.Schema(
            {
                vol.Optional(entity_id): EntitySelector(
                    EntitySelectorConfig(domain="light")
                )
                for entity_id in template_lights
            }
        )
        return self.async_show_form(step_id="light_map", data_schema=schema)

    def _apply_light_map(self, dropped: list[str]) -> None:
        """Rewrite the light section's entity ids through the mapping."""
        light = dict(self._bundle.get("kydax_light") or {})

        def _map(entity_id: str) -> str | None:
            if entity_id in dropped:
                return None
            return self._light_map.get(entity_id, entity_id)

        lights = {}
        for entity_id, values in (light.get("lights") or {}).items():
            mapped = _map(entity_id)
            if mapped:
                lights[mapped] = values
        light["lights"] = lights
        for key in ("zones", "pause_buttons"):
            items = []
            for item in light.get(key) or []:
                new_item = dict(item)
                new_item["lights"] = [
                    mapped
                    for mapped in (_map(e) for e in item.get("lights", []))
                    if mapped
                ]
                items.append(new_item)
            if items:
                light[key] = items
        self._bundle["kydax_light"] = light

    async def async_step_light_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No template lights: pick the managed lights, defaults applied."""
        if user_input is not None:
            light = dict(self._bundle.get("kydax_light") or {})
            light["lights"] = {
                entity_id: {"day": 90, "evening": 30, "night": 0}
                for entity_id in user_input.get("lights", [])
            }
            light.setdefault("pause_buttons", [])
            self._bundle["kydax_light"] = light
            return await self.async_step_switches()
        return self.async_show_form(
            step_id="light_pick",
            data_schema=vol.Schema(
                {
                    vol.Optional("lights", default=[]): EntitySelector(
                        EntitySelectorConfig(domain="light", multiple=True)
                    )
                }
            ),
        )

    # --- step 4: customer switches -----------------------------------------

    def _sound_channel_options(self) -> list[SelectOptionDict]:
        channels = (self._bundle.get("kydax_sound") or {}).get("channels", [])
        return [
            SelectOptionDict(
                value=str(channel["number"]),
                label=f"{channel.get('name', '?')} ({channel['number']})",
            )
            for channel in channels
        ]

    def _light_options(self) -> list[SelectOptionDict]:
        lights = (self._bundle.get("kydax_light") or {}).get("lights", {})
        return [SelectOptionDict(value=e, label=e) for e in lights]

    async def async_step_switches(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One customer pause switch per screen; sound and light paired."""
        channel_options = self._sound_channel_options()
        light_options = self._light_options()
        if not channel_options and not light_options:
            return await self.async_step_birthdays()
        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            if name:
                switch_id = uuid4().hex[:8]
                channels = [int(number) for number in user_input.get("channels", [])]
                if channels:
                    sound = self._bundle.setdefault("kydax_sound", {})
                    sound.setdefault("pause_groups", []).append(
                        {"id": switch_id, "name": name, "channels": channels}
                    )
                lights = list(user_input.get("lights", []))
                if lights:
                    light = self._bundle.setdefault("kydax_light", {})
                    light.setdefault("pause_buttons", []).append(
                        {"id": switch_id, "name": name, "lights": lights}
                    )
            if user_input.get("add_another"):
                return await self.async_step_switches()
            return await self.async_step_birthdays()
        schema_fields: dict[Any, Any] = {vol.Optional("name"): TextSelector()}
        if channel_options:
            schema_fields[vol.Optional("channels", default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=channel_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        if light_options:
            schema_fields[vol.Optional("lights", default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=light_options,
                    multiple=True,
                    mode=SelectSelectorMode.LIST,
                )
            )
        schema_fields[vol.Required("add_another", default=False)] = BooleanSelector()
        return self.async_show_form(
            step_id="switches", data_schema=vol.Schema(schema_fields)
        )

    # --- step 5: birthday / event presets -----------------------------------

    async def async_step_birthdays(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One event per screen (birthday preset on the Symetrix)."""
        if not self._bundle.get("kydax_sound", {}).get("host"):
            return await self.async_step_dashboard()
        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            if name and user_input.get("preset"):
                event: dict[str, Any] = {
                    "id": uuid4().hex[:8],
                    "name": name,
                    "preset": user_input["preset"],
                }
                if user_input.get("duration"):
                    event["duration"] = user_input["duration"]
                if user_input.get("return_preset"):
                    event["return_preset"] = user_input["return_preset"]
                sound = self._bundle.setdefault("kydax_sound", {})
                sound.setdefault("event_buttons", []).append(event)
            if user_input.get("add_another"):
                return await self.async_step_birthdays()
            return await self.async_step_dashboard()
        return self.async_show_form(
            step_id="birthdays",
            data_schema=vol.Schema(
                {
                    vol.Optional("name"): TextSelector(),
                    vol.Optional("preset"): _optional_int(1, 150),
                    vol.Optional("duration"): _optional_int(1, 3600),
                    vol.Optional("return_preset"): _optional_int(1, 150),
                    vol.Required("add_another", default=False): BooleanSelector(),
                }
            ),
        )

    # --- step 6: dashboard ----------------------------------------------------

    async def async_step_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        dashboard = dict(self._bundle.get("dashboard") or {})
        if user_input is not None:
            dashboard["title"] = user_input["title"].strip() or "Restaurant"
            dashboard["url_path"] = (
                user_input["url_path"].strip().lower() or "restaurant"
            )
            kiosk_default = bundle_lib.default_bundle()["dashboard"]["kiosk"]
            dashboard["kiosk"] = kiosk_default if user_input["kiosk"] else {}
            if user_input.get("background"):
                name = await self._async_save_background(user_input["background"])
                if name:
                    dashboard["background_image"] = f"/local/{WWW_SUBDIR}/{name}"
            self._bundle["dashboard"] = dashboard
            return await self.async_step_confirm()
        return self.async_show_form(
            step_id="dashboard",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "title", default=dashboard.get("title", "Restaurant")
                    ): TextSelector(),
                    vol.Required(
                        "url_path", default=dashboard.get("url_path", "restaurant")
                    ): TextSelector(),
                    vol.Required(
                        "kiosk", default=bool(dashboard.get("kiosk"))
                    ): BooleanSelector(),
                    vol.Optional("background"): FileSelector(
                        FileSelectorConfig(accept="image/*")
                    ),
                }
            ),
        )

    async def _async_save_background(self, file_id: str) -> str | None:
        def _copy() -> str | None:
            with process_uploaded_file(self.hass, file_id) as path:
                data = path.read_bytes()
            name = _detect_image_name(data)
            directory = self.hass.config.path("www", WWW_SUBDIR)
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, name), "wb") as handle:
                handle.write(data)
            return name

        try:
            return await self.hass.async_add_executor_job(_copy)
        except OSError:
            return None

    # --- step 7: confirm ------------------------------------------------------

    def _generate_default_views(self) -> None:
        """A sensible dashboard when the bundle brings none of its own."""
        dashboard = self._bundle.setdefault("dashboard", {})
        if dashboard.get("views"):
            return
        sound = self._bundle.get("kydax_sound") or {}
        light = self._bundle.get("kydax_light") or {}
        views: list[dict[str, Any]] = []

        volume_entities: list[str] = []
        if sound.get("host"):
            volume_entities.append("$sound:volume_level")
            if sound.get("languages"):
                volume_entities.append("$sound:language")
            volume_entities += [
                f"$sound:channel_{channel['number']}"
                for channel in sound.get("channels", [])
            ]
        if volume_entities:
            views.append(
                {
                    "title": "Volume",
                    "icon": "mdi:volume-high",
                    "path": "volume",
                    "cards": [{"type": "entities", "entities": volume_entities}],
                }
            )

        pause_entities = [
            f"$sound:pause_{group['id']}" for group in sound.get("pause_groups", [])
        ] + [
            f"$light:pause_{button['id']}"
            for button in light.get("pause_buttons", [])
        ]
        if pause_entities:
            views.append(
                {
                    "title": "Pauses",
                    "icon": "mdi:pause-circle",
                    "path": "pauses",
                    "cards": [{"type": "entities", "entities": pause_entities}],
                }
            )

        event_entities = [
            f"$sound:event_{event['id']}" for event in sound.get("event_buttons", [])
        ]
        if event_entities:
            views.append(
                {
                    "title": "Fêtes",
                    "icon": "mdi:party-popper",
                    "path": "fetes",
                    "cards": [{"type": "entities", "entities": event_entities}],
                }
            )

        if light.get("lights"):
            light_entities = ["$light:gradation"] + [
                f"$light:gradation_{zone['id']}" for zone in light.get("zones", [])
            ]
            views.append(
                {
                    "title": "Lumières",
                    "icon": "mdi:lightbulb-group",
                    "path": "lumieres",
                    "cards": [{"type": "entities", "entities": light_entities}],
                }
            )
        dashboard["views"] = views

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        sound = self._bundle.get("kydax_sound") or {}
        light = self._bundle.get("kydax_light") or {}
        if user_input is not None:
            self._generate_default_views()
            phase = PHASE_PENDING if user_input["start_now"] else PHASE_HOLD
            return self.async_create_entry(
                title=self._bundle["venue"].get("name") or "Kydax Bootstrap",
                data={},
                options={
                    CONF_BUNDLE: self._bundle,
                    CONF_PROVISIONING: {"phase": phase},
                },
            )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Required("start_now", default=True): BooleanSelector()}
            ),
            description_placeholders={
                "components": str(len(self._bundle.get("components", []))),
                "channels": str(len(sound.get("channels", []))),
                "lights": str(len(light.get("lights", {}))),
                "events": str(len(sound.get("event_buttons", []))),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> KydaxBootstrapOptionsFlow:
        return KydaxBootstrapOptionsFlow()


class KydaxBootstrapOptionsFlow(OptionsFlow):
    """Bundle export/import and provisioning control."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["provision", "export", "import"]
        )

    async def async_step_provision(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_PROVISIONING] = {"phase": PHASE_PENDING}
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="provision", data_schema=vol.Schema({})
        )

    async def async_step_export(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["path"].strip() or DEFAULT_EXPORT_FILE
            directory = self.hass.config.path("www")
            path = self.hass.config.path("www", name)
            payload = bundle_lib.export_payload(
                self.config_entry.options.get(CONF_BUNDLE, {})
            )

            def _write() -> None:
                os.makedirs(directory, exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)

            try:
                await self.hass.async_add_executor_job(_write)
                url = await _async_download_url(self.hass, directory, name)
            except OSError:
                errors["path"] = "write_failed"
            else:
                return self.async_abort(
                    reason="exported",
                    description_placeholders={"url": url, "path": path},
                )
        return self.async_show_form(
            step_id="export",
            data_schema=vol.Schema(
                {vol.Required("path", default=DEFAULT_EXPORT_FILE): TextSelector()}
            ),
            errors=errors,
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:

            def _read() -> Any:
                with process_uploaded_file(self.hass, user_input["file"]) as path:
                    with open(path, encoding="utf-8") as handle:
                        return json.load(handle)

            try:
                data = await self.hass.async_add_executor_job(_read)
            except (OSError, ValueError, KeyError):
                errors["file"] = "invalid_file"
            else:
                normalized = bundle_lib.normalize(data)
                problem = (
                    bundle_lib.validate(normalized)
                    if normalized
                    else "invalid_file"
                )
                if normalized is None or problem:
                    errors["file"] = problem or "invalid_file"
                else:
                    options = dict(self.config_entry.options)
                    options[CONF_BUNDLE] = normalized
                    return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="import",
            data_schema=vol.Schema(
                {
                    vol.Required("file"): FileSelector(
                        FileSelectorConfig(accept=".json,application/json")
                    )
                }
            ),
            errors=errors,
        )
