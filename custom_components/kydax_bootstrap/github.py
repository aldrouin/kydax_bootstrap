"""Thin GitHub releases client over Home Assistant's shared aiohttp session.

Deliberately independent from HACS: its backend API is private and has
broken between major versions, which is the one failure mode a
provisioning integration cannot afford. Unauthenticated GitHub allows 60
requests/hour per IP — plenty for a handful of venues.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import GITHUB_API

_LOGGER = logging.getLogger(__name__)

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "kydax-bootstrap",
}


class GitHubError(Exception):
    """GitHub could not deliver what was asked."""


async def _get_json(hass: HomeAssistant, url: str) -> Any:
    session = async_get_clientsession(hass)
    async with session.get(url, headers=_HEADERS, timeout=30) as response:
        if response.status != 200:
            raise GitHubError(f"GET {url} -> HTTP {response.status}")
        return await response.json()


async def async_get_release(
    hass: HomeAssistant, repo: str, version: str | None = None
) -> dict[str, Any]:
    """A release object; the latest one when version is empty or 'latest'."""
    if version and version != "latest":
        tag = version if version.startswith("v") else f"v{version}"
        try:
            return await _get_json(
                hass, f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}"
            )
        except GitHubError:
            # some repos tag without the v prefix
            return await _get_json(
                hass, f"{GITHUB_API}/repos/{repo}/releases/tags/{version}"
            )
    return await _get_json(hass, f"{GITHUB_API}/repos/{repo}/releases/latest")


def release_version(release: dict[str, Any]) -> str:
    return str(release.get("tag_name", "")).lstrip("v")


async def async_download(hass: HomeAssistant, url: str) -> bytes:
    """Download a zipball or release asset (follows redirects)."""
    session = async_get_clientsession(hass)
    async with session.get(
        url, headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=120
    ) as response:
        if response.status != 200:
            raise GitHubError(f"GET {url} -> HTTP {response.status}")
        return await response.read()


async def async_download_zipball(
    hass: HomeAssistant, release: dict[str, Any]
) -> bytes:
    url = release.get("zipball_url")
    if not url:
        raise GitHubError("release has no zipball_url")
    return await async_download(hass, url)


async def async_download_asset(
    hass: HomeAssistant, release: dict[str, Any], asset_name: str
) -> bytes:
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return await async_download(hass, asset["browser_download_url"])
    raise GitHubError(f"release {release.get('tag_name')} has no asset {asset_name}")
