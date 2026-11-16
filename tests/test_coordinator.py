"""Tests for EthosCoordinator and the API client's requests and error mapping."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.ethos.api import (
    EthosApiClient,
    EthosApiError,
    EthosAuthError,
)
from custom_components.ethos.coordinator import EthosCoordinator

from .conftest import HABIT_READ, HABIT_RUN, MOCK_TOKEN, MOCK_URL, TODAY, habit_with


async def test_update_keys_habits_by_id_in_order(hass, mock_api_client, mock_config_entry):
    coordinator = EthosCoordinator(hass, mock_config_entry, mock_api_client)
    data = await coordinator._async_update_data()

    mock_api_client.get_habits.assert_awaited_once_with(TODAY)
    assert data["today"] == TODAY
    assert list(data["habits"]) == [HABIT_RUN, HABIT_READ]


async def test_expired_session_starts_reauth(hass, mock_api_client, mock_config_entry):
    mock_api_client.get_habits.side_effect = EthosAuthError("UNAUTHENTICATED")
    with patch("custom_components.ethos.EthosApiClient", return_value=mock_api_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_server_error_retries_setup(hass, mock_api_client, mock_config_entry):
    mock_api_client.get_habits.side_effect = EthosApiError("boom")
    with patch("custom_components.ethos.EthosApiClient", return_value=mock_api_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_mark_applies_the_answer_without_refetching(
    hass, mock_api_client, mock_config_entry
):
    coordinator = EthosCoordinator(hass, mock_config_entry, mock_api_client)
    await coordinator.async_refresh()
    kept = habit_with(
        HABIT_READ,
        entries=[{"day": TODAY, "status": "done", "note": None, "partial": False}],
    )
    mock_api_client.mark_habit.return_value = kept

    await coordinator.async_mark(HABIT_READ)

    mock_api_client.mark_habit.assert_awaited_once_with(
        HABIT_READ, TODAY, TODAY, status="done", note=None, partial=False
    )
    assert coordinator.habit(HABIT_READ) == kept
    assert mock_api_client.get_habits.await_count == 1


async def test_refused_mark_is_a_home_assistant_error(hass, mock_api_client, mock_config_entry):
    coordinator = EthosCoordinator(hass, mock_config_entry, mock_api_client)
    await coordinator.async_refresh()
    mock_api_client.mark_habit.side_effect = EthosApiError("Two skips is the most a week allows")

    with pytest.raises(HomeAssistantError, match="Two skips"):
        await coordinator.async_mark(HABIT_RUN, status="skipped")


# ----------------------------------------------------------------------
# The client over HTTP
# ----------------------------------------------------------------------


def _response(status: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=payload)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.parametrize(
    ("status", "payload", "exc"),
    [
        (401, {}, EthosAuthError),
        (
            200,
            {"errors": [{"message": "Not signed in", "extensions": {"code": "UNAUTHENTICATED"}}]},
            EthosAuthError,
        ),
        (200, {"errors": [{"message": "Habit not found"}]}, EthosApiError),
    ],
)
async def test_graphql_error_mapping(status, payload, exc):
    session = MagicMock()
    session.post = MagicMock(return_value=_response(status, payload))
    client = EthosApiClient(MOCK_URL, MOCK_TOKEN, session)

    with pytest.raises(exc):
        await client.get_habits(TODAY)


async def test_get_habits_sends_today_and_bearer():
    session = MagicMock()
    session.post = MagicMock(return_value=_response(200, {"data": {"habits": []}}))
    client = EthosApiClient(MOCK_URL + "/", MOCK_TOKEN, session)

    assert await client.get_habits(TODAY) == []
    args, kwargs = session.post.call_args
    assert args[0] == f"{MOCK_URL}/graphql"
    assert kwargs["headers"] == {"Authorization": f"Bearer {MOCK_TOKEN}"}
    assert kwargs["json"]["variables"] == {"today": TODAY}
    query = kwargs["json"]["query"]
    assert "archivedAt: { isNull: true }" in query
    assert "current(today: $today)" in query


async def test_mark_habit_sends_the_day_and_status():
    session = MagicMock()
    session.post = MagicMock(
        return_value=_response(200, {"data": {"markHabit": {"id": HABIT_RUN}}})
    )
    client = EthosApiClient(MOCK_URL, MOCK_TOKEN, session)

    await client.mark_habit(HABIT_RUN, "2026-11-15", TODAY, status="skipped", note="Sick")
    variables = session.post.call_args.kwargs["json"]["variables"]
    assert variables == {
        "habitId": HABIT_RUN,
        "day": "2026-11-15",
        "status": "skipped",
        "note": "Sick",
        "partial": False,
        "today": TODAY,
    }
    json.dumps(session.post.call_args.kwargs["json"])  # serialisable as sent
