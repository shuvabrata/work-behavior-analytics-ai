"""API-runtime settings.

``ApiSettings`` extends the credential-free :class:`domain.settings.UISettings`
with everything only the API runtime may hold: the database URL, the data-store
credentials, the RabbitMQ URL, the connector-encryption key and the LLM provider
keys.

``DATABASE_URL`` deliberately has **no default**. That is what makes
``ApiSettings`` unconstructable in the UI runtime, which never receives a
database URL — the type system enforces the runtime boundary (Decision 3 of
plan 052).
"""

from domain.settings import UISettings
from pydantic import Field


class ApiSettings(UISettings):
    """The API runtime's settings — ``UISettings`` plus every credential."""

    # PostgreSQL configuration
    DATABASE_URL: str

    # Neo4j configuration
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    NEO4J_AI_LOOKUP_ENABLED: bool = True
    FF_NEO4J_USE_PROVIDER_PIPELINE: bool = False

    # RabbitMQ configuration
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Elasticsearch configuration
    ELASTICSEARCH_AI_LOOKUP_ENABLED: bool = True
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ELASTIC_PASSWORD: str = ""

    # Augmentation chain configuration
    AUGMENTATION_HISTORY_TURNS: int = 5  # prior turns passed to all chains for context resolution
    ES_CHAIN_MAX_RESULTS: int = 5  # max ES hits included in the LLM context block

    # MCP configuration
    GITHUB_MCP_ENABLED: bool = False
    ATLASSIAN_MCP_ENABLED: bool = False
    MAX_MCP_ITERATIONS: int = 3
    GITHUB_MCP_TOKEN: str = ""
    ATLASSIAN_MCP_TOKEN: str = ""
    GITHUB_MCP_SERVER_URL: str = "http://github-mcp:8082/"
    ATLASSIAN_MCP_SERVER_URL: str = "https://mcp.atlassian.com/v1/mcp"

    # LLM configuration (provider-agnostic)
    LLM_PROVIDER: str = "openai"
    LLM_MODEL: str = "gpt-5"
    MAX_TOKENS: int = 16000
    OPENAI_API_KEY: str = ""
    OPENAI_API_URL: str = "https://api.openai.com/v1/chat/completions"
    CUSTOM_API_TOKEN: str = ""
    CUSTOM_API_URL: str = ""
    CUSTOM_LLM_MODEL: str = ""

    # Connector encryption
    CONNECTOR_ENCRYPTION_KEY: str = ""

    # Connector / Producer configuration
    COMMIT_DAYS_LIMIT: int = 60
    PULL_REQUEST_DAYS_LIMIT: int = 60
    ISSUE_DAYS_LIMIT: int = 60
    IDENTITY_REFRESH_DAYS: int = 7
    MAX_TEAM_SIZE: int = 100
    JIRA_LOOKBACK_DAYS: int = 90
    JIRA_MAX_RESULTS_PER_PAGE: int = 100
    CONFLUENCE_LOOKBACK_DAYS: int = 60
    JIRA_EPIC_TEAM_FIELD: str = "Team"
    JIRA_ISSUE_TEAM_FIELD: str = "Team"
    JIRA_EPIC_START_DATE_FIELD: str = "created"
    JIRA_EPIC_DUE_DATE_FIELD: str = "duedate"
    API_SERVER: str = "http://api:8000/"
    CONFIGURATION_SOURCE: str = "SERVER"

    # Neo4j query timeout (should be less than HTTP_REQUEST_TIMEOUT to allow overhead)
    NEO4J_QUERY_TIMEOUT: int = 10

    # Activity Timeline mock data (DEV ONLY).
    # Empty = disabled. When set to one of the scenario names in
    # app.api.activity.v1.mock_data.MOCK_SCENARIOS, /api/v1/activity/timeline
    # and /suggest serve deterministic INVENTED data instead of querying the DB.
    # Never set this in a real deployment.
    TIMELINE_MOCK_SCENARIO: str = ""

    # Scheduler configuration
    # How often (in minutes) the scheduler wakes up to check for due connector scans.
    # Lower values reduce jitter but are still negligible overhead (one small DB query).
    SCHEDULER_TICK_MINUTES: int = Field(default=10, ge=1)

    # Retry-with-backoff configuration for producer API calls (in seconds)
    RETRY_BUDGET_SECONDS: int = Field(default=3600, ge=1)
    RETRY_BACKOFF_CAP_SECONDS: int = Field(default=30, ge=1)
    RETRY_BASE_DELAY_SECONDS: int = Field(default=1, ge=1)


settings = ApiSettings()  # type: ignore[call-arg]

# Backwards-compatible alias: ``Settings`` was the pre-split name of this class.
# Kept so existing importers (the API, and tests that construct it directly)
# do not have to be rewritten for what is otherwise a pure rename.
Settings = ApiSettings

__all__ = ["ApiSettings", "Settings", "settings"]
