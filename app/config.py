from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # ORCID OAuth settings
    orcid_client_id: str = ""
    orcid_client_secret: str = ""
    orcid_redirect_uri: str = "http://localhost:3000/auth/callback"
    orcid_environment: str = "sandbox"  # or 'production'

    # LLM API settings
    llm_provider: str = "anthropic"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-5-20250929"

    # Application settings
    secret_key: str = "dev-secret-key-change-in-production"
    database_path: str = "./claim_verification.db"
    max_file_size_mb: int = 10
    max_tokens: int = 200000

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    @property
    def orcid_auth_url(self) -> str:
        """Get ORCID authorization URL"""
        base = "https://orcid.org" if self.orcid_environment == "production" else "https://sandbox.orcid.org"
        return f"{base}/oauth/authorize"

    @property
    def orcid_token_url(self) -> str:
        """Get ORCID token URL"""
        base = "https://orcid.org" if self.orcid_environment == "production" else "https://sandbox.orcid.org"
        return f"{base}/oauth/token"

    @property
    def orcid_api_url(self) -> str:
        """Get ORCID API URL"""
        base = "https://pub.orcid.org" if self.orcid_environment == "production" else "https://pub.sandbox.orcid.org"
        return base

    @property
    def anthropic_api_key(self) -> str:
        """Get Anthropic API key (alias for llm_api_key)"""
        return self.llm_api_key

    @property
    def anthropic_model(self) -> str:
        """Get Anthropic model (alias for llm_model)"""
        return self.llm_model


settings = Settings()
