"""Ethos Home Assistant integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import voluptuous as vol
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import ConfigType

from .api import STATUS_DONE, STATUS_SKIPPED, EthosApiClient, TokenSource
from .const import (
    ATTR_DAY,
    ATTR_NOTE,
    ATTR_PARTIAL,
    ATTR_STATUS,
    AUTH_OIDC,
    CONF_ACCESS_TOKEN,
    CONF_AUTH_METHOD,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    PLATFORMS,
    SERVICE_CLEAR_HABIT,
    SERVICE_MARK_HABIT,
)
from .coordinator import EthosCoordinator
from .entity import habit_id_of
from .oidc import OidcTokenSource, TokenSet

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class EthosData:
    """Runtime data stored on the config entry."""

    coordinator: EthosCoordinator


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services. They act on a habit's "Done today" switch.

    A target may be the switch, or the habit's device (which also holds its
    progress sensor); either way the service reaches the habit.
    """
    async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_MARK_HABIT,
        entity_domain=SWITCH_DOMAIN,
        schema={
            vol.Optional(ATTR_DAY): cv.date,
            vol.Optional(ATTR_STATUS, default=STATUS_DONE): vol.In(
                [STATUS_DONE, STATUS_SKIPPED]
            ),
            vol.Optional(ATTR_NOTE): cv.string,
            vol.Optional(ATTR_PARTIAL, default=False): cv.boolean,
        },
        func="async_mark",
    )
    async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_CLEAR_HABIT,
        entity_domain=SWITCH_DOMAIN,
        schema={vol.Optional(ATTR_DAY): cv.date},
        func="async_clear",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ethos from a config entry."""
    session = async_get_clientsession(hass)
    token: str | TokenSource
    if entry.data.get(CONF_AUTH_METHOD) == AUTH_OIDC:

        def _save(tokens: TokenSet) -> None:
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_EXPIRES_AT: tokens.expires_at,
                },
            )

        token = OidcTokenSource(session, dict(entry.data), _save)
    else:
        token = entry.data[CONF_TOKEN]
    client = EthosApiClient(url=entry.data[CONF_URL], token=token, session=session)
    coordinator = EthosCoordinator(hass, entry, client)

    # Raises ConfigEntryAuthFailed (→ reauth) or ConfigEntryNotReady (→ retry).
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EthosData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _rename_devices() -> None:
        # A habit renamed in Ethos renames its device (a name set in HA wins).
        devices = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
            habit_id = habit_id_of(entry, device)
            habit = coordinator.habit(habit_id) if habit_id else None
            if habit and device.name != habit["name"]:
                devices.async_update_device(device.id, name=habit["name"])

    entry.async_on_unload(coordinator.async_add_listener(_rename_devices))

    @callback
    def _new_day(now: datetime) -> None:
        # Yesterday's ticks stop being today's, and a new period may begin.
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_track_time_change(hass, _new_day, hour=0, minute=0, second=5)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
