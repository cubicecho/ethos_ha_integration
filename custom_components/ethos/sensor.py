"""Ethos sensor platform: each habit's tally for the period today falls in."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EthosData
from .entity import EthosHabitEntity, add_habit_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data: EthosData = entry.runtime_data
    coordinator = data.coordinator
    add_habit_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda habit_id: [EthosProgressSensor(coordinator, entry, habit_id)],
    )


class EthosProgressSensor(EthosHabitEntity, SensorEntity):
    """Days kept in the current period (Ethos's ``current.done``).

    A habit is counted by the period, one period at a time, so this starts
    again at 0 when a new day, week or month begins. Ethos's tally rides along
    as attributes: what the period asks (``target``, and ``effective_target``
    once skips come off), the skips, and whether it is ``met``.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry, habit_id: str) -> None:
        super().__init__(coordinator, entry, habit_id, "progress")

    @property
    def _current(self) -> dict[str, Any] | None:
        habit = self.habit
        return habit.get("current") if habit else None

    @property
    def native_value(self) -> int | None:
        current = self._current
        return current["done"] if current else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        habit, current = self.habit, self._current
        if habit is None or current is None:
            return None
        return {
            "habit_id": self.habit_id,
            "period": habit.get("period"),
            "target": current["target"],
            "effective_target": current["effectiveTarget"],
            "skipped": current["skipped"],
            "remaining": max(current["effectiveTarget"] - current["done"], 0),
            "met": current["met"],
            "period_start": current["start"],
            # Ethos's ``end`` is exclusive (the day after); this is the last day.
            "period_end": _last_day(current["end"]),
        }


def _last_day(end: str) -> str:
    try:
        return (date.fromisoformat(end) - timedelta(days=1)).isoformat()
    except ValueError:
        return end
