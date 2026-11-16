# Ethos API used by this integration

Endpoint: `POST {url}/graphql` for queries and mutations. Ethos has no subscriptions.
The schema is generated from Ethos's Drizzle schema. Its SDL is `apps/ethos/server/__generated__/schema.graphql` (run `npm run codegen` in apps/ethos).

## Auth

- HTTP: `Authorization: Bearer <session token | provider access token>`.
- An expired or missing credential gets a GraphQL error with `extensions.code == "UNAUTHENTICATED"` on HTTP 200.
- Rows the caller doesn't own are `NOT_FOUND`, never `FORBIDDEN`.

### Discovery (no token)

```graphql
query AuthConfig {
  authConfig { magicLink secureLocalNet sso { name deviceClientId } }
}
```
`sso` is null when no provider is set up. `deviceClientId` is null until a device client exists: `OIDC_DEVICE_CLIENT_ID`, or the one pairing registers once the provider turns on its device grant. **`deviceClientId` and the metadata below come with apps/ethos PR #45.** Against an older server this query fails, and the config flow reports `cannot_connect`.

`GET {url}/.well-known/oauth-protected-resource` (RFC 9728): `{ "resource": <audience>, "authorization_servers": [<issuer>], "bearer_methods_supported": ["header"] }`. The audience is `OIDC_API_AUDIENCE`, which defaults to `<SERVER_URL>/graphql`.

### Provider device flow (RFC 8628, at the issuer)

The same as Telos's; see `oidc.py`. `scope=openid email offline_access`, `resource=<audience>`, refresh with `grant_type=refresh_token` + `resource`.

### Who am I

```graphql
query Me { users { id } }
```
`users` is scoped to the caller's own row.

### Sign-in (no token)

`signInMagicLink(email) { status token userId }`, then `magicLinkVerify(token) { token user { id } }`. These are the same as Telos's. Link format: `{APP_URL}/auth/verify?token=<token>`.

## Query

```graphql
query Habits($today: String!) {
  habits(
    where: { archivedAt: { isNull: true } }
    orderBy: { position: { direction: asc, priority: 1 } }
  ) {
    id name notes cue color period targetCount dailyAmount
    current(today: $today) { start end done skipped target effectiveTarget met }
    entries(where: { day: { eq: $today } }) { day status note partial amount dailyAmount }
  }
}
```
- `period` is `day` | `week` (ISO, Monday first) | `month`.
- `current.end` is exclusive (the day after the period's last).
- `dailyAmount` (≥ 1) is "times per day". `targetCount` counts days; `dailyAmount` is what one of them holds.
- `entries.amount` is the day's total. `entries.dailyAmount` snapshots the habit's at write time. A skip stores `1` / `1`, meaning nothing.
- `entries.day` is a `YYYY-MM-DD` string, filtered with `StringFilter`. `status` is `done` | `skipped`. No row means untouched.

## Mutations

| Mutation | Used for |
|----------|----------|
| `markHabit(habitId: ID!, day: String!, status: String = "done", note: String, partial: Boolean = false, amount: Int): Habit!` | switch on; amount number; `ethos.mark_habit`. Upserts the day's one row, rewriting `note` every time. `amount` left out is the whole daily amount; short of it is stored as partial. `BAD_USER_INPUT` for a bad status, a skip past the cap (`maxSkipsPerPeriod`, 2), `partial` or `amount` with a skip, an amount outside 1–100,000, or an archived habit |
| `clearHabit(habitId: ID!, day: String!): Habit!` | switch off; amount number set to 0; `ethos.clear_habit`. Leaves the day untouched rather than missed |

Both select the same habit fields as the query, with `$today` passed so `current` and `entries` are about the keeper's today.
