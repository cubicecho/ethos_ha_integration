"""Shared test fixtures."""
from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

MOCK_URL = "http://ethos.local:3000"
MOCK_EMAIL = "me@example.com"
MOCK_TOKEN = "session-token-abc"
MOCK_USER_ID = "11111111-1111-1111-1111-111111111111"
TODAY = "2026-11-16"  # a Monday

HABIT_RUN = "aaaaaaaa-0000-0000-0000-000000000001"
HABIT_READ = "aaaaaaaa-0000-0000-0000-000000000002"
HABIT_WATER = "aaaaaaaa-0000-0000-0000-000000000004"

# As EthosApiClient.get_habits returns them: counted for TODAY.
MOCK_HABITS = [
    {
        "id": HABIT_RUN,
        "name": "Run",
        "notes": None,
        "cue": "After coffee",
        "color": "#e11d48",
        "period": "week",
        "targetCount": 3,
        "dailyAmount": 1,
        "current": {
            "start": "2026-11-16",
            "end": "2026-11-23",
            "done": 1,
            "skipped": 0,
            "target": 3,
            "effectiveTarget": 3,
            "met": False,
        },
        "entries": [
            {
                "day": TODAY,
                "status": "done",
                "note": None,
                "partial": False,
                "amount": 1,
                "dailyAmount": 1,
            }
        ],
    },
    {
        "id": HABIT_READ,
        "name": "Read",
        "notes": None,
        "cue": None,
        "color": "#2563eb",
        "period": "day",
        "targetCount": 1,
        "dailyAmount": 1,
        "current": {
            "start": TODAY,
            "end": "2026-11-17",
            "done": 0,
            "skipped": 0,
            "target": 1,
            "effectiveTarget": 1,
            "met": False,
        },
        "entries": [],
    },
    {
        # Eight glasses a day, five so far, with a note to keep.
        "id": HABIT_WATER,
        "name": "Water",
        "notes": None,
        "cue": None,
        "color": "#0891b2",
        "period": "day",
        "targetCount": 1,
        "dailyAmount": 8,
        "current": {
            "start": TODAY,
            "end": "2026-11-17",
            "done": 1,
            "skipped": 0,
            "target": 1,
            "effectiveTarget": 1,
            "met": True,
        },
        "entries": [
            {
                "day": TODAY,
                "status": "done",
                "note": "Big bottle",
                "partial": True,
                "amount": 5,
                "dailyAmount": 8,
            }
        ],
    },
]


def habit_with(habit_id: str, **changes) -> dict:
    """A copy of a mock habit with fields replaced, as a mutation would answer."""
    habit = copy.deepcopy(next(h for h in MOCK_HABITS if h["id"] == habit_id))
    habit.update(changes)
    return habit


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom integrations in tests."""
    yield


@pytest.fixture(autouse=True)
def fixed_today():
    """Pin the keeper's today, whatever the clock says."""
    with patch("custom_components.ethos.coordinator.local_today", return_value=TODAY):
        yield


@pytest.fixture
def mock_api_client():
    """Return a mock EthosApiClient."""
    client = MagicMock()
    client.get_habits = AsyncMock(return_value=copy.deepcopy(MOCK_HABITS))
    client.mark_habit = AsyncMock(return_value=copy.deepcopy(MOCK_HABITS[0]))
    client.clear_habit = AsyncMock(return_value=copy.deepcopy(MOCK_HABITS[0]))
    return client


@pytest.fixture
def mock_config_entry(hass):
    """Return a mock config entry."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.ethos.const import (
        AUTH_SESSION,
        CONF_AUTH_METHOD,
        CONF_EMAIL,
        CONF_TOKEN,
        CONF_URL,
        CONF_USER_ID,
        DOMAIN,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{MOCK_URL}_{MOCK_USER_ID}",
        data={
            CONF_URL: MOCK_URL,
            CONF_USER_ID: MOCK_USER_ID,
            CONF_AUTH_METHOD: AUTH_SESSION,
            CONF_EMAIL: MOCK_EMAIL,
            CONF_TOKEN: MOCK_TOKEN,
        },
        title="ethos.local:3000",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(hass, mock_api_client, mock_config_entry):
    """Set the entry up against the mock client."""
    with patch("custom_components.ethos.EthosApiClient", return_value=mock_api_client):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry
