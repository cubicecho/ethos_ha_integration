"""Ethos number platform: how much of a habit today held, for habits that count."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EthosData
from .api import STATUS_DONE
from .const import MAX_AMOUNT
from .entity import EthosHabitEntity, add_habit_entities


def counts(habit: dict[str, Any]) -> bool:
    """Whether a habit asks for more than one of something a day ("8 glasses")."""
    return (habit.get("dailyAmount") or 1) > 1


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
        lambda habit_id: [EthosAmountTodayNumber(coordinator, entry, habit_id)],
        applies=counts,
    )


class EthosAmountTodayNumber(EthosHabitEntity, NumberEntity):
    """Today's total for a habit with a daily amount, like Ethos's stepper.

    0 is an untouched day. Setting 0 clears it; anything else keeps the day at
    that total, short of the amount a smaller version, past it the goal met.
    The day's note stays as it was. A skipped day reads 0, and setting an
    amount turns it into a kept day.

    Unavailable while the habit asks for just one a day: its switch says it all.
    """

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_AMOUNT
    _attr_native_step = 1

    def __init__(self, coordinator, entry: ConfigEntry, habit_id: str) -> None:
        super().__init__(coordinator, entry, habit_id, "amount_today")

    @property
    def available(self) -> bool:
        habit = self.habit
        return super().available and habit is not None and counts(habit)

    @property
    def native_value(self) -> int | None:
        if self.habit is None:
            return None
        entry = self.today_entry
        if entry is None or entry["status"] != STATUS_DONE:
            return 0
        return entry["amount"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        habit = self.habit
        if habit is None:
            return None
        return {"habit_id": self.habit_id, "daily_amount": habit["dailyAmount"]}

    async def async_set_native_value(self, value: float) -> None:
        if value != int(value):
            raise ServiceValidationError(f"An amount is a whole number, not {value}.")
        amount = int(value)
        if amount == 0:
            await self.coordinator.async_clear(self.habit_id)
            return
        # Ethos rewrites the note on every mark, so send the one the day has.
        note = (self.today_entry or {}).get("note")
        await self.coordinator.async_mark(self.habit_id, note=note, amount=amount)
