"""Ethos DataUpdateCoordinator."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import STATUS_DONE, EthosApiClient, EthosApiError, EthosAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def local_today() -> str:
    """Today in Home Assistant's own time zone, as Ethos keys a day: ``YYYY-MM-DD``.

    Ethos takes the day from the client, since a habit kept at 11pm on Tuesday
    is a Tuesday where the keeper is. Home Assistant's zone is where they are.
    """
    return dt_util.now().date().isoformat()


class EthosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches open habits from Ethos, each counted for today.

    ``data`` is ``{"today": "YYYY-MM-DD", "habits": {habit_id: habit}}``, the
    habits in the app's order. Polls every few minutes, at local midnight, and
    after every write.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: EthosApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client

    @property
    def habit_ids(self) -> list[str]:
        if self.data is None:
            return []
        return list(self.data["habits"])

    def habit(self, habit_id: str) -> dict[str, Any] | None:
        if self.data is None:
            return None
        return self.data["habits"].get(habit_id)

    async def _async_update_data(self) -> dict[str, Any]:
        today = local_today()
        try:
            habits = await self.client.get_habits(today)
        except EthosAuthError as err:
            raise ConfigEntryAuthFailed(f"Ethos session expired: {err}") from err
        except EthosApiError as err:
            raise UpdateFailed(f"Error fetching Ethos data: {err}") from err
        return {"today": today, "habits": {h["id"]: h for h in habits}}

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def async_mark(
        self,
        habit_id: str,
        day: date | str | None = None,
        status: str = STATUS_DONE,
        note: str | None = None,
        partial: bool = False,
    ) -> None:
        """Record a day of a habit (today unless ``day`` says otherwise)."""
        today = local_today()
        try:
            habit = await self.client.mark_habit(
                habit_id, _day(day, today), today, status=status, note=note, partial=partial
            )
        except EthosApiError as err:
            # e.g. a skip past the period's cap, or an archived habit.
            raise HomeAssistantError(f"Ethos could not mark the habit: {err}") from err
        self._apply(habit, today)

    async def async_clear(self, habit_id: str, day: date | str | None = None) -> None:
        """Remove a day's entry (today unless ``day`` says otherwise)."""
        today = local_today()
        try:
            habit = await self.client.clear_habit(habit_id, _day(day, today), today)
        except EthosApiError as err:
            raise HomeAssistantError(f"Ethos could not clear the habit: {err}") from err
        self._apply(habit, today)

    def _apply(self, habit: dict[str, Any], today: str) -> None:
        """Put a write's answer in place: it is the whole habit, counted for today."""
        if self.data is None or self.data["today"] != today:
            # The day turned over since the last poll; fetch everything afresh.
            self.hass.async_create_task(self.async_request_refresh())
            return
        habits = dict(self.data["habits"])
        habits[habit["id"]] = habit
        self.async_set_updated_data({"today": today, "habits": habits})


def _day(day: date | str | None, today: str) -> str:
    if day is None:
        return today
    return day.isoformat() if isinstance(day, date) else day
