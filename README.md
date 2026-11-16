# Ethos for Home Assistant

Brings your Ethos habits into Home Assistant. Every open habit gets a **Done today** switch, which you flip to tick today off, and a **Progress** sensor showing the days kept this period against what the habit asks. Two services cover the rest: skipping a day, marking another day, notes and smaller versions.

## Install

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cubicecho&repository=ethos_ha_integration&category=integration)

**HACS:** click the button above, or add this repository as a custom repository (category *Integration*). Install **Ethos**, then restart Home Assistant.

**Manual:** copy `custom_components/ethos` into your Home Assistant `config/custom_components/` directory and restart.

## Set up

[![Open your Home Assistant instance and start setting up Ethos.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ethos)

1. Click the button above, or go to *Settings → Devices & services → Add integration → Ethos.*
2. Enter your Ethos server URL (e.g. `http://192.168.1.10:3000`).
3. Pick how to sign in. Only the ways your Ethos instance offers are shown.
   - **Sign in with your provider in your browser.** This is for instances that sign in through an OIDC provider such as heautou. Home Assistant shows a link and a code. Open the link, sign in, check the code matches, and approve. Home Assistant carries on by itself. Your provider account must already be linked to Ethos, so sign in to Ethos with it once first.
   - **Email me a sign-in link.** Enter your email, then paste the link Ethos emails you (or just its token). This needs `SMTP_URL` on the Ethos server. On a server running with `SECURE_LOCAL_NET`, the address alone signs you in.

Provider tokens are refreshed automatically. If sign-in ever lapses, HA asks you to sign in again.

### Setting up provider sign-in (admin, once)

The Ethos server needs provider-token support (Ethos with `OIDC_DEVICE_CLIENT_ID` / `authConfig.sso.deviceClientId`). The provider must support the OAuth device flow and resource indicators. heautou does.

1. At the provider, register **Ethos as an API**. Its identifier is Ethos's audience: `OIDC_API_AUDIENCE`, which defaults to `<Ethos server URL>/graphql`.
2. Register a **public client** for Home Assistant (no secret) with the *device code* and *refresh token* grants, and allow it on the Ethos API. Pairing Ethos with heautou registers this one for you.
3. On Ethos, set `OIDC_DEVICE_CLIENT_ID` to that client's id, unless pairing registered it.

## What you get

Each habit is a device named after it, with:

| Entity | State | Attributes |
|--------|-------|------------|
| `switch.<habit>_done_today` | on when today is kept | `status` (`done` / `skipped`), `partial`, `note`, `cue`, `color` |
| `sensor.<habit>_progress` | days kept this period | `target`, `effective_target` (after skips), `skipped`, `remaining`, `met`, `period`, `period_start`, `period_end` |

Turning the switch **on** marks today kept. Turning it **off** clears today, so it counts as untouched, not missed. A skipped day shows as off with `status: skipped`. "Today" is Home Assistant's local date, and everything rolls over just after midnight. Archived habits go unavailable.

### Services

Target a habit's *Done today* switch, or the habit's device.

```yaml
# Skip yesterday
action: ethos.mark_habit
target:
  entity_id: switch.run_done_today
data:
  day: "2026-11-15"
  status: skipped
  note: Travelling

# A smaller version today
action: ethos.mark_habit
target:
  entity_id: switch.run_done_today
data:
  partial: true
  note: Just a mile

# Undo a day
action: ethos.clear_habit
target:
  entity_id: switch.run_done_today
data:
  day: "2026-11-15"
```

Ethos's rules still apply. A period allows at most two skips, a smaller version must be a kept day (not a skip), and an archived habit can't be marked. A refusal comes back as an error with Ethos's message.
