"""File-level install of integrations and frontend plugins.

Integrations: GitHub release zipball -> custom_components/<domain>, swapped
atomically (extract beside, move old away, move new in). Plugins: the
release asset copied to config/www/kydax/ and registered as a Lovelace
resource. All blocking work runs in the executor.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from . import github
from .const import WWW_SUBDIR

_LOGGER = logging.getLogger(__name__)


class InstallError(Exception):
    """The component could not be installed."""


def installed_version(hass: HomeAssistant, domain: str) -> str | None:
    """The manifest version of an installed custom integration (blocking)."""
    path = Path(hass.config.path("custom_components", domain, "manifest.json"))
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


async def async_installed_version(hass: HomeAssistant, domain: str) -> str | None:
    return await hass.async_add_executor_job(installed_version, hass, domain)


def _extract_integration(data: bytes, domain: str, target_root: Path) -> None:
    """Unpack custom_components/<domain> from a zipball into target_root."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [
            name
            for name in archive.namelist()
            if f"custom_components/{domain}/" in name and not name.endswith("/")
        ]
        if not members:
            raise InstallError(f"zipball contains no custom_components/{domain}")
        marker = f"custom_components/{domain}/"
        for name in members:
            relative = name.split(marker, 1)[1]
            destination = target_root / relative
            # the archive controls `relative`: never write outside the target
            if not destination.resolve().is_relative_to(target_root.resolve()):
                raise InstallError(f"unsafe path in zipball: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))


def _swap_in(hass: HomeAssistant, domain: str, staged: Path) -> None:
    """Replace custom_components/<domain> with the staged copy atomically-ish."""
    live = Path(hass.config.path("custom_components", domain))
    backup = live.with_name(f"{domain}.bak")
    if backup.exists():
        shutil.rmtree(backup)
    live.parent.mkdir(parents=True, exist_ok=True)
    if live.exists():
        live.rename(backup)
    try:
        staged.rename(live)
    except OSError:
        if backup.exists():
            backup.rename(live)  # roll back
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


async def async_install_integration(
    hass: HomeAssistant, component: dict[str, Any]
) -> str:
    """Install one integration component; returns the installed version."""
    domain = component["domain"]
    release = await github.async_get_release(
        hass, component["repo"], component.get("version")
    )
    version = github.release_version(release)
    data = await github.async_download_zipball(hass, release)

    def _install() -> None:
        staged = Path(hass.config.path("custom_components", f"{domain}.new"))
        if staged.exists():
            shutil.rmtree(staged)
        try:
            _extract_integration(data, domain, staged)
            _swap_in(hass, domain, staged)
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)

    await hass.async_add_executor_job(_install)
    _LOGGER.info("Installed %s %s from %s", domain, version, component["repo"])
    return version


async def async_install_plugin(hass: HomeAssistant, component: dict[str, Any]) -> str:
    """Install one frontend plugin asset; returns the installed version."""
    asset = component["asset"]
    release = await github.async_get_release(
        hass, component["repo"], component.get("version")
    )
    version = github.release_version(release)
    data = await github.async_download_asset(hass, release, asset)

    def _install() -> None:
        directory = Path(hass.config.path("www", WWW_SUBDIR))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / asset).write_bytes(data)

    await hass.async_add_executor_job(_install)
    _LOGGER.info("Installed plugin %s %s from %s", asset, version, component["repo"])
    return version


def plugin_resource_url(asset: str, version: str) -> str:
    """The Lovelace resource URL (version query busts browser caches)."""
    return f"/local/{WWW_SUBDIR}/{asset}?v={version}"


async def async_register_plugin_resource(
    hass: HomeAssistant, asset: str, version: str
) -> bool:
    """Register/refresh the Lovelace resource for a plugin asset.

    Uses the live resource collection (storage mode only). Returns False
    when resources cannot be managed — cosmetic, the file itself is in www.
    """
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA

        resources = hass.data[LOVELACE_DATA].resources
        prefix = f"/local/{WWW_SUBDIR}/{asset}"
        url = plugin_resource_url(asset, version)
        for item in resources.async_items():
            if str(item.get("url", "")).startswith(prefix):
                if item["url"] != url:
                    await resources.async_update_item(item["id"], {"url": url})
                return True
        await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception:  # noqa: BLE001 — internal API; degrade, never break setup
        _LOGGER.warning(
            "Could not register the Lovelace resource for %s; add "
            "/local/%s/%s manually in the dashboard resources",
            asset,
            WWW_SUBDIR,
            asset,
        )
        return False


async def async_register_in_hacs(hass: HomeAssistant, repo: str) -> None:
    """Best effort: make the repo visible in the HACS UI. Purely cosmetic."""
    try:
        hacs = hass.data.get("hacs")
        if hacs is None:
            return
        repositories = getattr(hacs, "repositories", None)
        if repositories is None or repositories.get_by_full_name(repo):
            return
        await hacs.async_register_repository(
            repository_full_name=repo, category="integration"
        )
        _LOGGER.debug("Registered %s in HACS", repo)
    except Exception:  # noqa: BLE001 — HACS internals are unstable by design
        _LOGGER.debug("HACS registration skipped for %s", repo, exc_info=True)
