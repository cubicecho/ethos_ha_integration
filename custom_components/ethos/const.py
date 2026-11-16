DOMAIN = "ethos"

CONF_URL = "url"
CONF_EMAIL = "email"
CONF_TOKEN = "token"
CONF_USER_ID = "user_id"

# Ethos has no subscriptions, so polling is what notices a day kept in the app.
DEFAULT_SCAN_INTERVAL = 5  # minutes

PLATFORMS = ["sensor", "switch"]

# How the entry signs in.
CONF_AUTH_METHOD = "auth_method"
AUTH_SESSION = "session"  # a better-auth session token in CONF_TOKEN
AUTH_OIDC = "oidc"  # an access token from Ethos's OIDC provider (device flow)

# For AUTH_OIDC entries.
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_ISSUER = "issuer"
CONF_AUDIENCE = "audience"
CONF_CLIENT_ID = "client_id"
CONF_TOKEN_ENDPOINT = "token_endpoint"

# Services.
SERVICE_MARK_HABIT = "mark_habit"
SERVICE_CLEAR_HABIT = "clear_habit"
ATTR_DAY = "day"
ATTR_STATUS = "status"
ATTR_NOTE = "note"
ATTR_PARTIAL = "partial"
