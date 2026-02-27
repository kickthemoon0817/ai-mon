from pydantic import BaseModel


class DailyUsage(BaseModel):
    date: str
    message_count: int = 0
    session_count: int = 0
    tool_call_count: int = 0
    token_count: int = 0
    conversation_count: int = 0
    file_size_bytes: int = 0


class ModelTokens(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class RateLimit(BaseModel):
    name: str  # e.g. "primary", "secondary", "weekly"
    used_percent: float = 0.0
    window_minutes: int = 0
    resets_at: str | None = None  # ISO timestamp
    used_tokens: int = 0  # raw token count for window
    model_breakdown: list[ModelTokens] = []  # per-model breakdown within window


class ServiceUsage(BaseModel):
    service: str
    daily_usage: list[DailyUsage] = []
    model_tokens: list[ModelTokens] = []
    total_messages: int = 0
    total_sessions: int = 0
    total_tokens: int = 0
    hour_counts: dict[str, int] = {}
    first_date: str | None = None
    last_date: str | None = None
    rate_limits: list[RateLimit] = []


class UsageSummary(BaseModel):
    services: list[ServiceUsage] = []
    last_refreshed: str | None = None
