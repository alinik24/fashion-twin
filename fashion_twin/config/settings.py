"""Central configuration — all settings from environment / .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ══════════════════════════════════════════════════════════════════════════
    # Database Configuration
    # ══════════════════════════════════════════════════════════════════════════

    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5433/fashion_twin"
    redis_url: str = "redis://localhost:6379/0"

    # ══════════════════════════════════════════════════════════════════════════
    # Qdrant Vector DB
    # ══════════════════════════════════════════════════════════════════════════

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "fashion_items"

    # ══════════════════════════════════════════════════════════════════════════
    # Vinted Marketplace
    # ══════════════════════════════════════════════════════════════════════════

    vinted_base_url: str = "https://www.vinted.co.uk"
    vinted_session_cookie: str = ""
    vinted_proxy: str = ""

    # ══════════════════════════════════════════════════════════════════════════
    # FashionCLIP (Local Image Embeddings)
    # ══════════════════════════════════════════════════════════════════════════

    embedding_model: str = "patrickjohncyh/fashion-clip"
    embedding_dim: int = 512
    embedding_batch_size: int = 32
    embedding_device: str = "cpu"  # cpu, cuda, or mps

    # ══════════════════════════════════════════════════════════════════════════
    # LLM Provider Selection
    # ══════════════════════════════════════════════════════════════════════════

    llm_primary_provider: Literal["openrouter", "api_provider", "local"] = "openrouter"

    # ── OpenRouter (Recommended) ──────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_vision_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_fast_model: str = "meta-llama/llama-3.1-70b-instruct"
    openrouter_reasoning_model: str = "anthropic/claude-3.5-sonnet"
    openrouter_budget_model: str = "meta-llama/llama-3.1-8b-instruct"

    # ── API Provider (Azure OpenAI, OpenAI, Claude, etc.) ────────────────────
    api_provider_endpoint: str = ""
    api_provider_key: str = ""
    api_provider_version: str = ""
    api_provider_model: str = ""

    # ── Text Embeddings API ───────────────────────────────────────────────────
    embedding_api_endpoint: str = ""
    embedding_api_key: str = ""
    embedding_api_model: str = "text-embedding-3-large"
    embedding_api_dim: int = 3072
    embedding_api_version: str = ""

    # ── Local LLM (Ollama) ────────────────────────────────────────────────────
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "llama3.1:8b"

    # ══════════════════════════════════════════════════════════════════════════
    # Task-Specific Model Assignments
    # ══════════════════════════════════════════════════════════════════════════

    llm_reward_model: str = "anthropic/claude-3.5-sonnet"
    llm_reward_provider: str = "openrouter"
    llm_fast_model: str = "meta-llama/llama-3.1-70b-instruct"
    llm_fast_provider: str = "openrouter"
    llm_reasoning_model: str = "anthropic/claude-3.5-sonnet"
    llm_reasoning_provider: str = "openrouter"
    llm_deal_model: str = "meta-llama/llama-3.1-70b-instruct"
    llm_deal_provider: str = "openrouter"

    # ══════════════════════════════════════════════════════════════════════════
    # Deal Hunting & Price Tracking
    # ══════════════════════════════════════════════════════════════════════════

    price_tracking_enabled: bool = True
    price_check_interval_hours: int = 6
    price_drop_alert_threshold: float = 0.15  # 15% drop
    price_drop_min_amount: float = 10.0

    # Deal scoring weights
    deal_score_price_weight: float = 0.40
    deal_score_history_weight: float = 0.30
    deal_score_condition_weight: float = 0.20
    deal_score_time_weight: float = 0.10

    # Deal quality thresholds
    deal_excellent_threshold: int = 80
    deal_good_threshold: int = 60
    deal_fair_threshold: int = 40

    # Notifications
    deal_alert_discord_webhook: str = ""
    deal_alert_telegram_bot_token: str = ""
    deal_alert_telegram_chat_id: str = ""
    deal_alert_email: str = ""

    # Hunter mode
    hunter_mode_enabled: bool = False
    hunter_scan_interval_minutes: int = 30
    hunter_max_price: float = 200.0
    hunter_min_deal_score: int = 70
    hunter_categories: str = "jackets,dresses,bags,shoes"
    hunter_priority_brands: str = "chanel,gucci,prada,hermes,celine"

    # ══════════════════════════════════════════════════════════════════════════
    # RLHF & Personalization
    # ══════════════════════════════════════════════════════════════════════════

    rlhf_beta: float = 0.1
    rlhf_min_pairs: int = 20
    rlhf_reward_scale: float = 10.0
    rlhf_llm_judge_enabled: bool = True
    rlhf_checkpoint_dir: Path = Path("./artefacts/rlhf")

    # ══════════════════════════════════════════════════════════════════════════
    # Tracker (Behavioral Signals)
    # ══════════════════════════════════════════════════════════════════════════

    tracker_default_domain: str = "fashion"
    tracker_dwell_threshold_sec: float = 3.0
    tracker_session_file: Path = Path("./data/tracker_session.json")
    tracker_consent_file: Path = Path("./data/consent.json")
    tracker_enabled_domains: str = "fashion"

    # ══════════════════════════════════════════════════════════════════════════
    # Style Profile & Rules
    # ══════════════════════════════════════════════════════════════════════════

    rules_file: Path = Path("./data/user_rules.json")
    style_profile_file: Path = Path("./data/style_profile.json")

    # ══════════════════════════════════════════════════════════════════════════
    # Trends
    # ══════════════════════════════════════════════════════════════════════════

    trend_refresh_hours: int = 24
    trend_sources: str = "vogue,lyst,vinted_trending"
    trend_llm_extraction: bool = True

    # ══════════════════════════════════════════════════════════════════════════
    # Scraping
    # ══════════════════════════════════════════════════════════════════════════

    scrape_delay_min: float = 1.5
    scrape_delay_max: float = 4.0
    scrape_max_pages: int = 10
    scrape_proxies: str = ""
    scrape_rotate_user_agents: bool = True

    # ══════════════════════════════════════════════════════════════════════════
    # Recommendation Engine
    # ══════════════════════════════════════════════════════════════════════════

    lightfm_epochs: int = 30
    lightfm_num_threads: int = 4
    lightfm_learning_rate: float = 0.05
    lightfm_loss: Literal["warp", "bpr", "logistic"] = "warp"

    # Hybrid ranking weights
    ranker_collaborative_weight: float = 0.4
    ranker_content_weight: float = 0.3
    ranker_bandit_weight: float = 0.3

    model_save_dir: Path = Path("./artefacts")

    # ══════════════════════════════════════════════════════════════════════════
    # Advanced Features
    # ══════════════════════════════════════════════════════════════════════════

    outfit_compatibility_enabled: bool = False
    outfit_compatibility_model: str = "clip"

    attribute_extraction_enabled: bool = True
    attribute_extraction_model: str = "fashionpedia"

    sustainability_scoring_enabled: bool = False
    sustainability_blocklist: str = "polyester,acrylic,nylon"

    auto_purchase_enabled: bool = False
    auto_purchase_max_price: float = 50.0
    auto_purchase_min_score: int = 90

    # ══════════════════════════════════════════════════════════════════════════
    # Logging & Monitoring
    # ══════════════════════════════════════════════════════════════════════════

    log_level: str = "INFO"
    log_file: Path = Path("./logs/fashion_twin.log")
    sentry_dsn: str = ""

    performance_monitoring_enabled: bool = False
    slow_query_threshold_ms: int = 1000

    # ══════════════════════════════════════════════════════════════════════════
    # Helper Methods
    # ══════════════════════════════════════════════════════════════════════════

    def ensure_dirs(self) -> None:
        """Create necessary directories."""
        for d in [
            self.model_save_dir,
            self.rlhf_checkpoint_dir,
            self.tracker_session_file.parent,
            self.rules_file.parent,
            self.log_file.parent,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def enabled_domains_list(self) -> list[str]:
        """Parse enabled tracking domains."""
        if self.tracker_enabled_domains.strip().lower() == "all":
            return ["all"]
        return [d.strip() for d in self.tracker_enabled_domains.split(",") if d.strip()]

    @property
    def hunter_categories_list(self) -> list[str]:
        """Parse hunter mode categories."""
        return [c.strip() for c in self.hunter_categories.split(",") if c.strip()]

    @property
    def hunter_priority_brands_list(self) -> list[str]:
        """Parse hunter mode priority brands."""
        return [b.strip().lower() for b in self.hunter_priority_brands.split(",") if b.strip()]

    @property
    def sustainability_blocklist_items(self) -> list[str]:
        """Parse sustainability blocklist."""
        return [m.strip().lower() for m in self.sustainability_blocklist.split(",") if m.strip()]

    @property
    def scrape_proxies_list(self) -> list[str]:
        """Parse proxy list."""
        if not self.scrape_proxies.strip():
            return []
        return [p.strip() for p in self.scrape_proxies.split(",") if p.strip()]

    def get_llm_config(self, task: str = "general") -> dict:
        """
        Get LLM configuration for a specific task.

        Args:
            task: One of 'reward', 'fast', 'reasoning', 'deal', 'general'

        Returns:
            dict with 'provider', 'model', 'base_url', 'api_key'
        """
        task_map = {
            "reward": (self.llm_reward_provider, self.llm_reward_model),
            "fast": (self.llm_fast_provider, self.llm_fast_model),
            "reasoning": (self.llm_reasoning_provider, self.llm_reasoning_model),
            "deal": (self.llm_deal_provider, self.llm_deal_model),
            "general": (self.llm_primary_provider, self.openrouter_vision_model),
        }

        provider, model = task_map.get(task, task_map["general"])

        config = {
            "provider": provider,
            "model": model,
        }

        # Add provider-specific credentials
        if provider == "openrouter":
            config["base_url"] = self.openrouter_base_url
            config["api_key"] = self.openrouter_api_key
        elif provider == "api_provider":
            config["base_url"] = self.api_provider_endpoint
            config["api_key"] = self.api_provider_key
            config["api_version"] = self.api_provider_version
        elif provider == "local":
            config["base_url"] = self.local_llm_base_url
            config["api_key"] = "local"
            config["model"] = self.local_llm_model

        return config


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
