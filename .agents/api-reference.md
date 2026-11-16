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
    id name notes cue color period targetCount
    current(today: $today) { start end done skipped target effectiveTarget met }
    entries(where: { day: { eq: $today } }) { day status note partial }
  }
}
```
- `period` is `day` | `week` (ISO, Monday first) | `month`.
- `current.end` is exclusive (the day after the period's last).
- `entries.day` is a `YYYY-MM-DD` string, filtered with `StringFilter`. `status` is `done` | `skipped`. No row means untouched.

## Mutations

| Mutation | Used for |
|----------|----------|
| `markHabit(habitId: ID!, day: String!, status: String = "done", note: String, partial: Boolean = false): Habit!` | switch on; `ethos.mark_habit`. Upserts the day's one row. `BAD_USER_INPUT` for a bad status, a skip past the cap (`maxSkipsPerPeriod`, 2), `partial` with a skip, or an archived habit |
| `clearHabit(habitId: ID!, day: String!): Habit!` | switch off; `ethos.clear_habit`. Leaves the day untouched rather than missed |

Both select the same habit fields as the query, with `$today` passed so `current` and `entries` are about the keeper's today.
