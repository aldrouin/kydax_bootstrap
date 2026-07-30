"""Runtime hub for Kydax Bootstrap: provisioning state machine + updater."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from . import dashboard as dashboard_builder
from . import entries as entry_manager
from . import github, installer
from .bundle import (
    SIBLING_DOMAINS,
    integration_components,
    plugin_components,
)
from .const import (
    AUTO_UPDATE_HOUR,
    AUTO_UPDATE_WINDOW_MIN,
    CONF_BUNDLE,
    CONF_PROVISIONING,
    CRITICAL_MARKER,
    DOMAIN,
    ERROR_PREFIX,
    PHASE_DASHBOARD,
    PHASE_DONE,
    PHASE_ENTRIES,
    PHASE_FINAL_RESTART,
    PHASE_HOLD,
    PHASE_INSTALL,
    PHASE_PENDING,
    PHASE_RESTART,
    RESTART_DELAY_S,
    signal_update,
)

_LOGGER = logging.getLogger(__name__)

_HEARTBEAT = timedelta(seconds=60)


def _versions_differ(installed: str | None, wanted: str) -> bool:
    if installed is None:
        return True
    try:
        from awesomeversion import AwesomeVersion

        return AwesomeVersion(installed) != AwesomeVersion(wanted)
    except Exception:  # noqa: BLE001 — comparison must never crash the flow
        return installed != wanted


class KydaxBootstrapHub:
    """Owns the provisioning state machine and the centralized updater."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsubs: list = []
        self._work_lock = asyncio.Lock()
        # options snapshot without the provisioning key: the update listener
        # skips the reload when only provisioning progress changed
        self.significant = self._significant_options(entry.options)

        self.auto_update_enabled: bool = False
        self._last_auto_update_date: date | None = None
        self.update_info: dict[str, dict[str, Any]] = {}
        self.last_error: str | None = None
        self.dropped_placeholders: list[str] = []

    # --- accessors ----------------------------------------------------------

    @staticmethod
    def _significant_options(options: dict) -> dict:
        return {k: v for k, v in options.items() if k != CONF_PROVISIONING}

    @property
    def bundle(self) -> dict[str, Any]:
        return self.entry.options.get(CONF_BUNDLE, {})

    @property
    def provisioning(self) -> dict[str, Any]:
        return self.entry.options.get(CONF_PROVISIONING, {})

    @property
    def phase(self) -> str:
        return self.provisioning.get("phase", PHASE_HOLD)

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_heartbeat, _HEARTBEAT)
        )
        if self.hass.state is CoreState.running:
            self._kickoff()
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._async_on_started
                )
            )
        self._dispatch()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_on_started(self, _event) -> None:
        self._kickoff()

    @callback
    def _kickoff(self) -> None:
        if self.phase in (PHASE_HOLD, PHASE_DONE):
            return
        self.entry.async_create_background_task(
            self.hass, self.async_resume(), "kydax_bootstrap_provision"
        )

    # --- provisioning state machine -----------------------------------------

    def set_phase(self, phase: str, error: str | None = None) -> None:
        provisioning = dict(self.provisioning)
        provisioning["phase"] = phase
        provisioning["error"] = error
        options = {**self.entry.options, CONF_PROVISIONING: provisioning}
        self.last_error = error
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self._dispatch()

    def _record_installed(self, domain_or_asset: str, version: str) -> None:
        provisioning = dict(self.provisioning)
        installed = dict(provisioning.get("installed", {}))
        installed[domain_or_asset] = version
        provisioning["installed"] = installed
        options = {**self.entry.options, CONF_PROVISIONING: provisioning}
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def async_resume(self) -> None:
        """Drive the machine from the stored phase to done (or error)."""
        if self._work_lock.locked():
            return
        async with self._work_lock:
            phase = self.phase
            if phase.startswith(ERROR_PREFIX):
                phase = phase.removeprefix(ERROR_PREFIX)
            try:
                if phase in (PHASE_PENDING, PHASE_INSTALL):
                    await self._phase_install()
                    return  # either restarted or advanced internally
                if phase == PHASE_RESTART:
                    self.set_phase(PHASE_ENTRIES)
                    await self._phase_entries()
                    await self._phase_dashboard()
                    return
                if phase == PHASE_ENTRIES:
                    await self._phase_entries()
                    await self._phase_dashboard()
                    return
                if phase == PHASE_DASHBOARD:
                    await self._phase_dashboard()
                    return
                if phase == PHASE_FINAL_RESTART:
                    self.set_phase(PHASE_DONE)
            except Exception as err:  # noqa: BLE001 — surface, allow retry
                _LOGGER.exception("Provisioning failed during %s", phase)
                self.set_phase(f"{ERROR_PREFIX}{phase}", str(err))

    async def _phase_install(self) -> None:
        self.set_phase(PHASE_INSTALL)
        files_changed = False
        for component in integration_components(self.bundle):
            domain = component["domain"]
            wanted = str(component.get("version") or "latest")
            installed = await installer.async_installed_version(self.hass, domain)
            need = installed is None if wanted == "latest" else _versions_differ(
                installed, wanted
            )
            if not need:
                continue
            version = await installer.async_install_integration(self.hass, component)
            self._record_installed(domain, version)
            await installer.async_register_in_hacs(self.hass, component["repo"])
            files_changed = True
        for component in plugin_components(self.bundle):
            version = await installer.async_install_plugin(self.hass, component)
            self._record_installed(component["asset"], version)
            await installer.async_register_plugin_resource(
                self.hass, component["asset"], version
            )
        if files_changed:
            self.set_phase(PHASE_RESTART)
            self._restart("provision_restart")
            return
        self.set_phase(PHASE_ENTRIES)
        await self._phase_entries()
        await self._phase_dashboard()

    async def _phase_entries(self) -> None:
        self.set_phase(PHASE_ENTRIES)
        for domain in SIBLING_DOMAINS:
            section = self.bundle.get(domain) or {}
            outcome = await entry_manager.async_apply_section(
                self.hass, domain, section
            )
            if outcome != "skipped" and not await entry_manager.async_wait_loaded(
                self.hass, domain
            ):
                raise entry_manager.EntryError(f"{domain} did not reach LOADED")

    async def _phase_dashboard(self) -> None:
        self.set_phase(PHASE_DASHBOARD)
        section = self.bundle.get("dashboard") or {}
        if not section.get("views"):
            self.set_phase(PHASE_DONE)
            return
        created_new, dropped = await dashboard_builder.async_build(
            self.hass, section
        )
        self.dropped_placeholders = dropped
        if created_new:
            self.set_phase(PHASE_FINAL_RESTART)
            self._restart("dashboard_restart")
            return
        self.set_phase(PHASE_DONE)

    def _restart(self, kind: str) -> None:
        persistent_notification.async_create(
            self.hass,
            "Kydax Bootstrap redémarre Home Assistant dans quelques secondes "
            "pour terminer l'installation. / Kydax Bootstrap is restarting "
            "Home Assistant in a few seconds to finish the installation.",
            title="Kydax Bootstrap",
            notification_id=f"kydax_bootstrap_{kind}",
        )

        async def _do_restart() -> None:
            await asyncio.sleep(RESTART_DELAY_S)
            await self.hass.services.async_call("homeassistant", "restart", {})

        self.entry.async_create_background_task(
            self.hass, _do_restart(), f"kydax_bootstrap_{kind}"
        )

    # --- centralized auto-update --------------------------------------------

    async def _async_heartbeat(self, now: datetime) -> None:
        await self._async_maybe_auto_update(now)

    async def _async_maybe_auto_update(self, now: datetime) -> None:
        if self.phase != PHASE_DONE and self.phase != PHASE_HOLD:
            return  # never fight a provisioning run
        if now.hour != AUTO_UPDATE_HOUR or now.minute >= AUTO_UPDATE_WINDOW_MIN:
            return
        if self._last_auto_update_date == now.date():
            return
        self._last_auto_update_date = now.date()
        try:
            pending = await self.async_check_updates()
        except Exception:  # noqa: BLE001 — a GitHub hiccup must not break HA
            _LOGGER.exception("Update check failed")
            return
        to_install = [
            component
            for component, info in pending
            if self.auto_update_enabled or info.get("critical")
        ]
        if not to_install:
            return
        _LOGGER.info(
            "Auto-updating %d kydax component(s)",
            len(to_install),
        )
        try:
            await self.async_install_updates(to_install)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Auto-update failed")

    async def async_check_updates(self) -> list[tuple[dict, dict]]:
        """Refresh update_info; returns the components with a newer release."""
        pending: list[tuple[dict, dict]] = []
        info: dict[str, dict[str, Any]] = {}
        for component in self.bundle.get("components", []):
            repo = component["repo"]
            key = component.get("domain") or component.get("asset") or repo
            if component.get("type") == "integration":
                installed = await installer.async_installed_version(
                    self.hass, component["domain"]
                )
            else:
                installed = self.provisioning.get("installed", {}).get(
                    component.get("asset")
                )
            try:
                release = await github.async_get_release(self.hass, repo)
            except github.GitHubError as err:
                info[key] = {"installed": installed, "error": str(err)}
                continue
            latest = github.release_version(release)
            critical = CRITICAL_MARKER in (release.get("body") or "").lower()
            entry_info = {
                "installed": installed,
                "latest": latest,
                "critical": critical,
                "pending": _versions_differ(installed, latest),
            }
            info[key] = entry_info
            if entry_info["pending"]:
                pending.append((component, entry_info))
        info["_checked"] = {"at": dt_util.now().isoformat()}
        self.update_info = info
        self._dispatch()
        return pending

    async def async_install_updates(self, components: list[dict]) -> None:
        """Install the given components' latest releases, then restart once."""
        for component in components:
            if component.get("type") == "integration":
                version = await installer.async_install_integration(
                    self.hass, {**component, "version": "latest"}
                )
                self._record_installed(component["domain"], version)
            else:
                version = await installer.async_install_plugin(
                    self.hass, {**component, "version": "latest"}
                )
                self._record_installed(component["asset"], version)
                await installer.async_register_plugin_resource(
                    self.hass, component["asset"], version
                )
        self._restart("update_restart")

    @callback
    def _dispatch(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))
