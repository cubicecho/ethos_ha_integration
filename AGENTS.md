# Project: Ethos — Home Assistant Integration

A Home Assistant custom integration that connects to an [Ethos](../../apps/ethos) instance (a habit tracker) to surface each open habit as:
- a **"Done today" switch**: on when today is kept; on ticks today, off clears it
- a **"Progress" sensor**: days kept in the period today falls in, with Ethos's tally as attributes
- two **services**, `ethos.mark_habit` and `ethos.clear_habit`, for skips, other days, notes and smaller versions

Built from [telos-ha-integration](../telos-ha-integration). Sign-in, the config flow and `oidc.py` are the same, renamed. Users configure a server URL. The integration then signs in as them, through Ethos's OIDC provider (device flow) or with a magic link, whichever the instance offers.

## Commands

```bash
# Test environment (do not install the package itself: an editable install's
# path hook breaks HA's custom-integration loader; pytest puts "." on the path)
uv venv .venv && uv pip install --python .venv/bin/python pytest pytest-asyncio pytest-homeassistant-custom-component aiohttp ruff mypy

.venv/bin/pytest                                  # tests
.venv/bin/mypy custom_components/ethos/           # types
.venv/bin/ruff check custom_components/ tests/    # lint
```

## Tech Stack

| Choice | Why |
|--------|-----|
| **aiohttp** | HA's standard async HTTP client; reuse HA's session via `async_get_clientsession` |
| **DataUpdateCoordinator** | Single shared poller for all entities; 5-min interval, a refresh at local midnight, and each write's answer merged straight in |

## Key Conventions

- All config stored in `entry.data`: `url`, `user_id`, `auth_method`, plus `email`/`token` for a session or the OIDC tokens (see `.agents/integration-structure.md` → Sign-in)
- `entry.runtime_data` holds the typed `EthosData(coordinator=...)` dataclass
- `EthosApiClient` owns all HTTP. The coordinator calls client methods, and entities call the coordinator
- Auth: `Authorization: Bearer <token>` on every request. The token is a better-auth session, or an access token from Ethos's OIDC provider with Ethos as its audience

## Sign-in

Same two ways as Telos:

- **Through the OIDC provider (heautou), by device flow** (`oidc.py`, RFC 8628). Ethos's `/.well-known/oauth-protected-resource` (RFC 9728) names the provider and Ethos's audience. `authConfig.sso.deviceClientId` names the public client. Needs the Ethos server's provider-token support (apps/ethos PR #45). Without it, `deviceClientId` is not in the schema and the probe fails. The provider account must already be linked to an Ethos account (sign in to Ethos with the provider once).
- **By magic link** (`signInMagicLink` → `magicLinkVerify`), when the instance emails links (or under `SECURE_LOCAL_NET`).

When either lapses, Ethos answers `UNAUTHENTICATED`, the coordinator raises `ConfigEntryAuthFailed`, and HA starts the reauth flow.

## Guard clauses

Raise `EthosConnectionError` for network failures, and `EthosAuthError` for 401/403 or a GraphQL `UNAUTHENTICATED` error. Any other GraphQL error is an `EthosApiError` carrying the server's messages. Writes (switch, services) turn `EthosApiError` into `HomeAssistantError`, so a refusal reaches the user. Examples: a third skip in a period, or an archived habit.

## Ethos rules the integration respects

- **The day is the keeper's.** Ethos takes `today` from the client. The integration sends Home Assistant's local date (`coordinator.local_today()`) to `current(today:)`, to the `entries` filter, and as the default `day` of every write. It refreshes just after local midnight so yesterday's tick stops reading as today's.
- **Recording a day goes only through `markHabit` / `clearHabit`.** There is no generated CRUD for entries. Marking a day again rewrites its one row.
- **A skip is not a miss.** `status: skipped` is a deliberate decline, capped per period by the server. The switch reads off for a skipped day and says `status: skipped`. Turning it on overwrites the skip with a tick.
- **A smaller version (`partial`) is a kept day,** only with `status: done`.
- **Writes return the habit,** counted for the `today` sent, so the coordinator merges the answer (`_apply`) rather than refetching.
- **Archived habits** drop out of the query (`archivedAt: { isNull: true }`). Their entities go unavailable, and their history stays in Ethos.

## Agent File Convention

All planning, structure, and API reference docs live in `.agents/`. Always add new files to the reference list below.

## Agent Reference Files

- [`.agents/integration-structure.md`](.agents/integration-structure.md) — File layout, platform map, entity hierarchy, data flow
- [`.agents/api-reference.md`](.agents/api-reference.md) — GraphQL queries and mutations used by this integration
