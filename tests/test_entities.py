"""Tests for the habit switch, the progress sensor and the services."""
from __future__ import annotations

import copy
from datetime import date

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from custom_components.ethos.api import EthosApiError
from custom_components.ethos.const import DOMAIN

from .conftest import HABIT_READ, HABIT_RUN, MOCK_HABITS, TODAY, habit_with


def _habit_device(hass, entry, habit_id):
    devices = dr.async_get(hass)
    return next(
        d
        for d in dr.async_entries_for_config_entry(devices, entry.entry_id)
        if (DOMAIN, f"{entry.entry_id}_{habit_id}") in d.identifiers
    )

RUN_SWITCH = "switch.run_done_today"
READ_SWITCH = "switch.read_done_today"
RUN_PROGRESS = "sensor.run_progress"


async def test_switch_shows_today(hass, setup_integration):
    run = hass.states.get(RUN_SWITCH)
    assert run.state == STATE_ON
    assert run.attributes["status"] == "done"
    assert run.attributes["cue"] == "After coffee"
    assert hass.states.get(READ_SWITCH).state == STATE_OFF


async def test_skipped_day_reads_off(hass, mock_api_client, mock_config_entry):
    habits = copy.deepcopy(MOCK_HABITS)
    habits[1]["entries"] = [{"day": TODAY, "status": "skipped", "note": None, "partial": False}]
    mock_api_client.get_habits.return_value = habits
    from unittest.mock import patch

    with patch("custom_components.ethos.EthosApiClient", return_value=mock_api_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(READ_SWITCH)
    assert state.state == STATE_OFF
    assert state.attributes["status"] == "skipped"


async def test_progress_sensor(hass, setup_integration):
    state = hass.states.get(RUN_PROGRESS)
    assert state.state == "1"
    assert state.attributes["target"] == 3
    assert state.attributes["remaining"] == 2
    assert state.attributes["met"] is False
    assert state.attributes["period"] == "week"
    assert state.attributes["period_start"] == "2026-11-16"
    assert state.attributes["period_end"] == "2026-11-22"


async def test_turn_on_marks_today(hass, setup_integration, mock_api_client):
    mock_api_client.mark_habit.return_value = habit_with(
        HABIT_READ,
        entries=[{"day": TODAY, "status": "done", "note": None, "partial": False}],
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": READ_SWITCH}, blocking=True
    )

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_READ, TODAY, TODAY, status="done", note=None, partial=False
    )
    assert hass.states.get(READ_SWITCH).state == STATE_ON


async def test_turn_off_clears_today(hass, setup_integration, mock_api_client):
    mock_api_client.clear_habit.return_value = habit_with(HABIT_RUN, entries=[])
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": RUN_SWITCH}, blocking=True
    )

    mock_api_client.clear_habit.assert_awaited_once_with(HABIT_RUN, TODAY, TODAY)
    assert hass.states.get(RUN_SWITCH).state == STATE_OFF


async def test_mark_service_with_day_status_and_note(hass, setup_integration, mock_api_client):
    await hass.services.async_call(
        DOMAIN,
        "mark_habit",
        {
            "entity_id": RUN_SWITCH,
            "day": "2026-11-15",
            "status": "skipped",
            "note": "Travelling",
        },
        blocking=True,
    )

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_RUN, "2026-11-15", TODAY, status="skipped", note="Travelling", partial=False
    )
    day = mock_api_client.mark_habit.await_args.args[1]
    assert day == date(2026, 11, 15).isoformat()


async def test_mark_service_targets_a_habit_device(hass, setup_integration, mock_api_client):
    device = _habit_device(hass, setup_integration, HABIT_READ)
    assert device.name == "Read"

    await hass.services.async_call(
        DOMAIN, "mark_habit", {"device_id": device.id, "partial": True}, blocking=True
    )

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_READ, TODAY, TODAY, status="done", note=None, partial=True
    )


async def test_clear_service(hass, setup_integration, mock_api_client):
    await hass.services.async_call(
        DOMAIN, "clear_habit", {"entity_id": RUN_SWITCH, "day": "2026-11-14"}, blocking=True
    )
    mock_api_client.clear_habit.assert_awaited_once_with(HABIT_RUN, "2026-11-14", TODAY)


async def test_refusal_reaches_the_caller(hass, setup_integration, mock_api_client):
    mock_api_client.mark_habit.side_effect = EthosApiError("That habit is archived")
    with pytest.raises(HomeAssistantError, match="archived"):
        await hass.services.async_call(
            DOMAIN, "mark_habit", {"entity_id": RUN_SWITCH}, blocking=True
        )


async def test_habits_come_and_go(hass, setup_integration, mock_api_client):
    coordinator = setup_integration.runtime_data.coordinator
    new = habit_with(HABIT_READ, id="aaaaaaaa-0000-0000-0000-000000000003", name="Stretch")
    mock_api_client.get_habits.return_value = [copy.deepcopy(MOCK_HABITS[1]), new]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("switch.stretch_done_today") is not None
    assert hass.states.get("sensor.stretch_progress") is not None
    # Run was archived: its entities stay, unavailable.
    assert hass.states.get(RUN_SWITCH).state == STATE_UNAVAILABLE


async def test_rename_follows_ethos(hass, setup_integration, mock_api_client):
    coordinator = setup_integration.runtime_data.coordinator
    mock_api_client.get_habits.return_value = [
        habit_with(HABIT_RUN, name="Jog"),
        copy.deepcopy(MOCK_HABITS[1]),
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _habit_device(hass, setup_integration, HABIT_RUN).name == "Jog"


async def test_unload(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
