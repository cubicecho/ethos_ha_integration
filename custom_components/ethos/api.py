"""Ethos API client."""
from __future__ import annotations

import logging
from typing import Any, Protocol

import aiohttp

_LOGGER = logging.getLogger(__name__)

GRAPHQL_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Entry statuses Ethos records. An untouched day has no entry at all.
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"

# Selected on every habit read and write, so the coordinator's rows and a
# mutation's answer have the same shape. ``current`` and ``entries`` are both
# about the caller's own today: Ethos takes the day from the client, because a
# day is the keeper's, not the server's.
_HABIT_FIELDS = """
  id name notes cue color period targetCount dailyAmount
  current(today: $today) { start end done skipped target effectiveTarget met }
  entries(where: { day: { eq: $today } }) { day status note partial amount dailyAmount }
"""


class EthosApiError(Exception):
    """Base exception for Ethos API errors.

    ``code`` is the first GraphQL error's ``extensions.code`` (e.g.
    ``BAD_USER_INPUT``, ``TOO_MANY_REQUESTS``), when the server gave one.
    """

    def __init__(self, message: str = "", code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class EthosConnectionError(EthosApiError):
    """Failed to connect to the Ethos server."""


class EthosAuthError(EthosApiError):
    """The session token is missing, invalid or expired."""


class TokenSource(Protocol):
    """Where the client gets the bearer it sends."""

    async def async_token(self) -> str | None:
        """The bearer to send now, refreshed first if it is about to expire."""

    async def async_refresh(self) -> bool:
        """Get a new bearer after Ethos refused one. False when there is no way to."""


class StaticToken:
    """A bearer that never changes: a better-auth session, or none at all."""

    def __init__(self, token: str | None) -> None:
        self._token = token

    async def async_token(self) -> str | None:
        return self._token

    async def async_refresh(self) -> bool:
        return False


class EthosApiClient:
    """Async client for the Ethos GraphQL API.

    The integration signs in as a person. ``token`` is either a better-auth
    session token, or a TokenSource handing out access tokens from Ethos's OIDC
    provider (see oidc.py). Both are sent as ``Authorization: Bearer <token>``.
    It is None only for the sign-in calls.
    """

    def __init__(
        self,
        url: str,
        token: str | TokenSource | None,
        session: aiohttp.ClientSession,
    ) -> None:
        self._url = url.rstrip("/")
        self._graphql_url = f"{self._url}/graphql"
        self._auth: TokenSource = (
            token if token is not None and not isinstance(token, str) else StaticToken(token)
        )
        self._session = session

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._session

    @property
    def url(self) -> str:
        return self._url

    # ------------------------------------------------------------------
    # Sign-in (no session needed)
    # ------------------------------------------------------------------

    async def sign_in_magic_link(self, email: str) -> dict[str, Any]:
        """Ask Ethos to email a sign-in link.

        Under ``SECURE_LOCAL_NET`` no link is sent and the answer already holds
        a session (``token``/``userId``). Otherwise both are None and the link
        arrives by email. An instance with no mail server refuses with
        ``BAD_USER_INPUT``; the sign-in limiter answers ``TOO_MANY_REQUESTS``.
        """
        result = await self._graphql(
            """
            mutation SignInMagicLink($email: String!) {
              signInMagicLink(email: $email) { status token userId }
            }
            """,
            variables={"email": email},
        )
        return result["data"]["signInMagicLink"]

    async def magic_link_verify(self, token: str) -> dict[str, Any]:
        """Trade a sign-in link's token for a session: ``{"token", "userId"}``."""
        result = await self._graphql(
            """
            mutation MagicLinkVerify($token: String!) {
              magicLinkVerify(token: $token) { token user { id } }
            }
            """,
            variables={"token": token},
        )
        answer = result["data"]["magicLinkVerify"]
        return {"token": answer["token"], "userId": answer["user"]["id"]}

    async def get_auth_config(self) -> dict[str, Any]:
        """What the instance offers for signing in. Readable before signing in."""
        result = await self._graphql(
            """
            query AuthConfig {
              authConfig { magicLink secureLocalNet sso { name deviceClientId } }
            }
            """
        )
        return result["data"]["authConfig"]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_user_id(self) -> str:
        """The signed-in person's Ethos user id. ``users`` lists only the caller."""
        result = await self._graphql("query Me { users { id } }")
        users = result["data"]["users"]
        if not users:
            raise EthosAuthError("Ethos does not know who this is")
        return users[0]["id"]

    async def get_habits(self, today: str) -> list[dict[str, Any]]:
        """Open (non-archived) habits in the app's order, each counted for ``today``.

        ``today`` is the keeper's ``YYYY-MM-DD``. ``current`` is the period it
        falls in, and ``entries`` holds today's entry, if there is one.
        """
        result = await self._graphql(
            f"""
            query Habits($today: String!) {{
              habits(
                where: {{ archivedAt: {{ isNull: true }} }}
                orderBy: {{ position: {{ direction: asc, priority: 1 }} }}
              ) {{ {_HABIT_FIELDS} }}
            }}
            """,
            variables={"today": today},
        )
        return result["data"]["habits"]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def mark_habit(
        self,
        habit_id: str,
        day: str,
        today: str,
        status: str = STATUS_DONE,
        note: str | None = None,
        partial: bool = False,
        amount: int | None = None,
    ) -> dict[str, Any]:
        """Record one day of a habit. The day is the key: marking it again rewrites it.

        ``status`` is ``done`` or ``skipped``. ``partial`` (a smaller version)
        is only for a kept day. ``amount`` is the day's total, never a step;
        left out, a kept day is the habit's whole daily amount, and one short
        of it is stored as a smaller version. Ethos refuses an archived habit,
        a skip past the period's cap, and an amount on a skip. ``note`` is
        rewritten on every mark, so leaving it out clears the day's.
        ``today`` only shapes the answer.
        """
        result = await self._graphql(
            f"""
            mutation MarkHabit(
              $habitId: ID!, $day: String!, $status: String, $note: String,
              $partial: Boolean, $amount: Int, $today: String!
            ) {{
              markHabit(
                habitId: $habitId, day: $day, status: $status, note: $note,
                partial: $partial, amount: $amount
              ) {{ {_HABIT_FIELDS} }}
            }}
            """,
            variables={
                "habitId": habit_id,
                "day": day,
                "status": status,
                "note": note,
                "partial": partial,
                "amount": amount,
                "today": today,
            },
        )
        return result["data"]["markHabit"]

    async def clear_habit(self, habit_id: str, day: str, today: str) -> dict[str, Any]:
        """Remove a day's entry, leaving the day untouched rather than missed."""
        result = await self._graphql(
            f"""
            mutation ClearHabit($habitId: ID!, $day: String!, $today: String!) {{
              clearHabit(habitId: $habitId, day: $day) {{ {_HABIT_FIELDS} }}
            }}
            """,
            variables={"habitId": habit_id, "day": day, "today": today},
        )
        return result["data"]["clearHabit"]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            return await self._post(payload, await self._auth.async_token())
        except EthosAuthError:
            # An access token can be refused before its own expiry (revoked,
            # or the clocks disagree): get a new one and try once more.
            if not await self._auth.async_refresh():
                raise
            return await self._post(payload, await self._auth.async_token())

    async def _post(self, payload: dict[str, Any], token: str | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        try:
            async with self._session.post(
                self._graphql_url,
                json=payload,
                headers=headers,
                timeout=GRAPHQL_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise EthosAuthError(f"GraphQL returned {resp.status}")
                resp.raise_for_status()
                data = await resp.json()
        except EthosApiError:
            raise
        except aiohttp.ClientConnectionError as err:
            raise EthosConnectionError(
                f"Cannot connect to {self._graphql_url}"
            ) from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise EthosConnectionError(f"Request failed: {err}") from err

        errors = data.get("errors")
        if errors:
            _raise_for_errors(errors)

        return data


def _raise_for_errors(errors: list[dict[str, Any]]) -> None:
    """Raise the GraphQL errors as the matching EthosApiError."""
    message = "; ".join(str(e.get("message", e)) for e in errors)
    # Ethos answers an expired or missing credential with UNAUTHENTICATED on
    # HTTP 200, as GraphQL servers do.
    codes = [(e.get("extensions") or {}).get("code") for e in errors]
    if "UNAUTHENTICATED" in codes:
        raise EthosAuthError(message, "UNAUTHENTICATED")
    raise EthosApiError(message, next((c for c in codes if c), None))
