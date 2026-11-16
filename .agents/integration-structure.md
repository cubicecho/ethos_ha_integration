# Integration structure

```
custom_components/ethos/
├── __init__.py       # async_setup: the two entity services; async_setup_entry: client → coordinator → first refresh → platforms → device renames, midnight refresh
├── api.py            # EthosApiClient: all Ethos HTTP; TokenSource / StaticToken; EthosApiError (with .code) / EthosConnectionError / EthosAuthError
├── config_flow.py    # user (URL) → authConfig → method menu → browser (device flow progress) | email → link → entry; reauth_confirm → same menu
├── const.py          # DOMAIN, CONF_* keys, AUTH_SESSION / AUTH_OIDC, scan interval, PLATFORMS, service names and fields
├── oidc.py           # provider side: RFC 9728 metadata, discovery, device flow (RFC 8628), refresh; OidcTokenSource
├── coordinator.py    # EthosCoordinator: habits counted for local today; async_mark / async_clear
├── entity.py         # EthosHabitEntity base, one device per habit, add_habit_entities (adds new habits as they appear)
├── switch.py         # EthosDoneTodaySwitch, plus the entity-service handlers
├── sensor.py         # EthosProgressSensor
├── number.py         # EthosAmountTodayNumber, for habits with dailyAmount > 1
├── services.yaml
├── icons.json
├── manifest.json
├── strings.json      # copied verbatim to translations/en.json
└── translations/en.json
tests/
├── conftest.py       # MOCK_HABITS counted for TODAY, fixed local_today, mock_api_client, setup_integration
├── test_config_flow.py  # menu, device flow (gated polling), magic link, reauth (from telos)
├── test_oidc.py      # device flow + refresh over HTTP, token source, retry on UNAUTHENTICATED (from telos)
├── test_coordinator.py  # data shape, reauth/retry on setup, merge-on-write, request shapes, GraphQL error mapping
└── test_entities.py  # switch, sensor, amount number, services (entity and device targets), habits appearing/archived, renames
```

## Platforms

| Platform | Entity | Translation key | One per |
|----------|--------|-----------------|---------|
| `switch` | `EthosDoneTodaySwitch` | `done_today` → "Done today" | open (non-archived) habit |
| `sensor` | `EthosProgressSensor` | `progress` → "Progress" | open habit |
| `number` | `EthosAmountTodayNumber` | `amount_today` → "Amount today" | open habit with `dailyAmount > 1` |

Each habit is one device (`identifiers={(DOMAIN, f"{entry_id}_{habit_id}")}`, named after the habit and renamed when Ethos renames it), so entity ids come out as `switch.<habit>_done_today` / `sensor.<habit>_progress` / `number.<habit>_amount_today`.
Entity unique id: `{entry_id}_{habit_id}_{key}`.

### Switch

- `is_on`: today's entry exists with `status == "done"`.
- On → `markHabit(today, done)`. Off → `clearHabit(today)`.
- Attributes: `habit_id`, `status` (`done` / `skipped` / null), `partial`, `note`, `amount` (kept days only), `daily_amount`, `cue`, `color`.
- On a habit that counts, on records the whole amount (no `amount` sent), and a short day is still on.

### Number

- Added by `add_habit_entities(..., applies=counts)`: a habit is offered again on every update, so one that starts asking for more than one a day gets its number then. One that goes back to 1 leaves it unavailable.
- State: today's `amount` when kept, else 0 (untouched or skipped). Box mode, 0 to `MAX_AMOUNT`, step 1.
- Set 0 → `clearHabit(today)`. Set n → `markHabit(today, done, amount=n, partial=false, note=<the day's note>)`, as the app's stepper does, since `markHabit` rewrites the note.
- Attributes: `habit_id`, `daily_amount`.

### Sensor

- State: `current.done`, with `state_class: measurement`. It restarts at 0 each period.
- Attributes: `habit_id`, `period` (`day`/`week`/`month`), `target`, `effective_target` (after skips), `skipped`, `remaining`, `met`, `period_start`, `period_end` (the last day, inclusive; Ethos's own `end` is exclusive).

### Services

Registered with `async_register_platform_entity_service` on the `switch` entity domain, so a target is a habit's switch, or its device.

| Service | Fields | Calls |
|---------|--------|-------|
| `ethos.mark_habit` | `day` (date, default today), `status` (`done`/`skipped`, default `done`), `note`, `partial` (bool), `amount` (1–100,000, default the whole daily amount) | `markHabit` |
| `ethos.clear_habit` | `day` (date, default today) | `clearHabit` |

## Data flow

`coordinator.data`:

```python
{
    "today": "YYYY-MM-DD",           # HA's local date when it was fetched
    "habits": {habit_id: {           # in Ethos's order (position)
        "id", "name", "notes", "cue", "color", "period", "targetCount", "dailyAmount",
        "current": {"start", "end", "done", "skipped", "target", "effectiveTarget", "met"},
        "entries": [{"day", "status", "note", "partial", "amount", "dailyAmount"}],   # today's, if any
    }},
}
```

- **Polling:** every 5 min (`DEFAULT_SCAN_INTERVAL`). Ethos has no subscriptions.
- **Midnight:** `async_track_time_change(00:00:05)` requests a refresh, so "today" moves on.
- **Writes** return the whole habit counted for the `today` sent. `_apply` puts it in place with `async_set_updated_data`, with no refetch. If the day turned over since the last poll, it refreshes instead.
- **New habits** get entities at once (a coordinator listener in `add_habit_entities`). An archived or deleted habit leaves its entities unavailable.

## Sign-in

`entry.data[CONF_AUTH_METHOD]` says how the entry signs in:

| `auth_method` | Data | Bearer |
|---------------|------|--------|
| `session` | `email`, `token` | the better-auth session token, as is (`StaticToken`) |
| `oidc` | `access_token`, `refresh_token`, `expires_at`, `issuer`, `audience`, `client_id`, `token_endpoint` | `OidcTokenSource`: refreshes within 60 s of expiry (one at a time, behind a lock) and saves new tokens to the entry |

`EthosApiClient._graphql` asks the token source for a bearer on every call. On `UNAUTHENTICATED` it asks the source to refresh, and retries once (a session can't refresh, so it raises at once). A refused refresh (`invalid_grant`) is an `EthosAuthError`, so the coordinator starts reauth.
