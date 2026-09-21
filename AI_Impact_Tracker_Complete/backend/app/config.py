from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # Gemini
    gemini_api_key: str = ""
    gemini_key_fallback: str = ""
    gemini_model: str = "gemini-3.5-flash"
    # A structured evidence-analysis response can legitimately take longer
    # than a short chat completion.  This remains environment-configurable.
    gemini_timeout_seconds: float = 90.0
    gemini_rate_limit_max_wait_seconds: float = 45.0

    # Research providers
    serper_api_key: str = ""
    jina_api_key: str = ""

    # Optional Microsoft Foundry Grounding with Bing Search.  This is the
    # current Foundry Responses API integration, not the retired Bing Web
    # Search v7 API.  Leave disabled/unset to run the normal Serper-only flow.
    bing_web_search_enabled: bool = False
    azure_foundry_project_endpoint: str = ""
    azure_foundry_bearer_token: str = ""
    azure_foundry_model_deployment: str = ""
    bing_project_connection_id: str = ""
    bing_search_market: str = "en-US"
    bing_search_language: str = "en"
    bing_search_result_count: int = 8

    # Company / financial data
    companies_house_api_key: str = ""
    sec_user_agent: str = "AIImpactTracker contact@example.com"
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com/stable"

    # Application
    database_url: str = "sqlite+aiosqlite:///./ai_impact_tracker.db"
    frontend_origin: str = "http://localhost:3000"

    # Research limits
    max_candidates: int = 8
    shortlist_size: int = 3
    max_pages_per_stage: int = 6


settings = Settings()
