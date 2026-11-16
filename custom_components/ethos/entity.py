"""What every Ethos habit entity shares: its habit, and the habit's device."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import (
    DeviceEntry,
    DeviceEntryType,
    DeviceInfo,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EthosCoordinator


def habit_device_id(entry: ConfigEntry, habit_id: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_{habit_id}")


def habit_id_of(entry: ConfigEntry, device: DeviceEntry) -> str | None:
    """The habit a device of this entry stands for, from its identifier."""
    prefix = f"{entry.entry_id}_"
    for domain, identifier in device.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            return identifier.removeprefix(prefix)
    return None


def habit_device_info(entry: ConfigEntry, habit: dict[str, Any]) -> DeviceInfo:
    """One device per habit, holding its switch and its sensor."""
    return DeviceInfo(
        identifiers={habit_device_id(entry, habit["id"])},
        name=habit["name"],
        manufacturer="Ethos",
        model="Habit",
        entry_type=DeviceEntryType.SERVICE,
    )


def add_habit_entities(
    entry: ConfigEntry,
    coordinator: EthosCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[str], Iterable[Entity]],
) -> None:
    """Add a platform's entities for every habit, and for each new one as it appears."""
    known: set[str] = set()

    @callback
    def _add_new_habits() -> None:
        new = [h for h in coordinator.habit_ids if h not in known]
        known.update(new)
        if new:
            async_add_entities(entity for habit_id in new for entity in build(habit_id))

    _add_new_habits()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_habits))


class EthosHabitEntity(CoordinatorEntity[EthosCoordinator]):
    """One facet of one habit. Unavailable once the habit is archived or deleted."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: EthosCoordinator, entry: ConfigEntry, habit_id: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self.habit_id = habit_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{habit_id}_{key}"
        habit = coordinator.habit(habit_id)
        assert habit is not None
        self._attr_device_info = habit_device_info(entry, habit)

    @property
    def habit(self) -> dict[str, Any] | None:
        return self.coordinator.habit(self.habit_id)

    @property
    def available(self) -> bool:
        # An archived habit drops out of the feed; its history stays in Ethos.
        return super().available and self.habit is not None

    @property
    def today_entry(self) -> dict[str, Any] | None:
        habit = self.habit
        if habit is None or self.coordinator.data is None:
            return None
        today = self.coordinator.data["today"]
        return next((e for e in habit.get("entries") or [] if e["day"] == today), None)
