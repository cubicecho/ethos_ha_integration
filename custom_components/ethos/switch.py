"""Ethos switch platform: whether each habit is done today, and the way to tick it."""
from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EthosData
from .api import STATUS_DONE
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
        lambda habit_id: [EthosDoneTodaySwitch(coordinator, entry, habit_id)],
    )


class EthosDoneTodaySwitch(EthosHabitEntity, SwitchEntity):
    """On when today is kept. On ticks today; off clears it (untouched, not missed).

    A skipped day reads as off, with ``status: skipped``. Skipping, other days,
    notes and smaller versions go through the ``ethos.mark_habit`` service.
    """

    def __init__(self, coordinator, entry: ConfigEntry, habit_id: str) -> None:
        super().__init__(coordinator, entry, habit_id, "done_today")

    @property
    def is_on(self) -> bool | None:
        if self.habit is None:
            return None
        entry = self.today_entry
        return entry is not None and entry["status"] == STATUS_DONE

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        habit = self.habit
        if habit is None:
            return None
        entry = self.today_entry or {}
        return {
            "habit_id": self.habit_id,
            "status": entry.get("status"),
            "partial": bool(entry.get("partial")),
            "note": entry.get("note"),
            "cue": habit.get("cue"),
            "color": habit.get("color"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_mark(self.habit_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_clear(self.habit_id)

    # Entity services (registered in __init__.async_setup).

    async def async_mark(
        self,
        day: date | None = None,
        status: str = STATUS_DONE,
        note: str | None = None,
        partial: bool = False,
    ) -> None:
        await self.coordinator.async_mark(
            self.habit_id, day, status=status, note=note, partial=partial
        )

    async def async_clear(self, day: date | None = None) -> None:
        await self.coordinator.async_clear(self.habit_id, day)
