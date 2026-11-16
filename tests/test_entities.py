"""Tests for the habit switch, the progress sensor and the services."""
from __future__ import annotations

import copy
from datetime import date

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.ethos.api import EthosApiError
from custom_components.ethos.const import DOMAIN

from .conftest import HABIT_READ, HABIT_RUN, HABIT_WATER, MOCK_HABITS, TODAY, habit_with


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
WATER_SWITCH = "switch.water_done_today"
WATER_AMOUNT = "number.water_amount_today"


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
        HABIT_READ, TODAY, TODAY, status="done", note=None, partial=False, amount=None
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
        HABIT_RUN,
        "2026-11-15",
        TODAY,
        status="skipped",
        note="Travelling",
        partial=False,
        amount=None,
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
        HABIT_READ, TODAY, TODAY, status="done", note=None, partial=True, amount=None
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


async def test_amount_only_for_habits_that_count(hass, setup_integration):
    state = hass.states.get(WATER_AMOUNT)
    assert state.state == "5"
    assert state.attributes["daily_amount"] == 8
    assert state.attributes["max"] == 100_000
    assert hass.states.get("number.run_amount_today") is None
    assert hass.states.get("number.read_amount_today") is None


async def test_short_day_is_on_with_its_amount(hass, setup_integration):
    state = hass.states.get(WATER_SWITCH)
    assert state.state == STATE_ON
    assert state.attributes["partial"] is True
    assert state.attributes["amount"] == 5
    assert state.attributes["daily_amount"] == 8


async def test_set_amount_marks_the_total_and_keeps_the_note(
    hass, setup_integration, mock_api_client
):
    full = habit_with(HABIT_WATER)
    full["entries"][0].update(amount=8, partial=False)
    mock_api_client.mark_habit.return_value = full

    await hass.services.async_call(
        "number", "set_value", {"entity_id": WATER_AMOUNT, "value": 8}, blocking=True
    )

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_WATER, TODAY, TODAY, status="done", note="Big bottle", partial=False, amount=8
    )
    assert hass.states.get(WATER_AMOUNT).state == "8"


async def test_set_amount_to_zero_clears_today(hass, setup_integration, mock_api_client):
    mock_api_client.clear_habit.return_value = habit_with(HABIT_WATER, entries=[])

    await hass.services.async_call(
        "number", "set_value", {"entity_id": WATER_AMOUNT, "value": 0}, blocking=True
    )

    mock_api_client.clear_habit.assert_awaited_once_with(HABIT_WATER, TODAY, TODAY)
    mock_api_client.mark_habit.assert_not_awaited()
    assert hass.states.get(WATER_AMOUNT).state == "0"


async def test_set_amount_refuses_a_fraction(hass, setup_integration, mock_api_client):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": WATER_AMOUNT, "value": 2.5}, blocking=True
        )
    mock_api_client.mark_habit.assert_not_awaited()


async def test_skipped_day_reads_zero(hass, mock_api_client, mock_config_entry):
    habits = copy.deepcopy(MOCK_HABITS)
    habits[2]["entries"] = [
        {
            "day": TODAY,
            "status": "skipped",
            "note": None,
            "partial": False,
            "amount": 1,
            "dailyAmount": 1,
        }
    ]
    mock_api_client.get_habits.return_value = habits
    from unittest.mock import patch

    with patch("custom_components.ethos.EthosApiClient", return_value=mock_api_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(WATER_AMOUNT).state == "0"
    assert hass.states.get(WATER_SWITCH).attributes["amount"] is None


async def test_amount_follows_the_daily_amount(hass, setup_integration, mock_api_client):
    coordinator = setup_integration.runtime_data.coordinator
    # Read starts asking for 3 a day, and Water goes back to one.
    mock_api_client.get_habits.return_value = [
        copy.deepcopy(MOCK_HABITS[0]),
        habit_with(HABIT_READ, dailyAmount=3),
        habit_with(HABIT_WATER, dailyAmount=1),
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("number.read_amount_today").state == "0"
    assert hass.states.get(WATER_AMOUNT).state == STATE_UNAVAILABLE


async def test_mark_service_with_amount(hass, setup_integration, mock_api_client):
    await hass.services.async_call(
        DOMAIN,
        "mark_habit",
        {"entity_id": WATER_SWITCH, "day": "2026-11-15", "amount": 3},
        blocking=True,
    )

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_WATER, "2026-11-15", TODAY, status="done", note=None, partial=False, amount=3
    )


async def test_unload(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
