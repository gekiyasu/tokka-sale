import os
from dataclasses import dataclass
from dotenv import load_dotenv

# プロジェクトルートの .env を読み込み
load_dotenv()

@dataclass
class Config:
    # Amazon
    amazon_tag: str = os.getenv("AMAZON_ASSOCIATE_TAG", "default-22")
    
    # Keepa API
    keepa_api_key: str = os.getenv("KEEPA_API_KEY", "")
    
    # Filter
    min_discount_percent: int = int(os.getenv("MIN_DISCOUNT_PERCENT", "20"))
    min_rating: float = float(os.getenv("MIN_RATING", "3.8"))
    min_reviews_count: int = int(os.getenv("MIN_REVIEWS_COUNT", "10"))
    check_interval_minutes: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "120"))
    interval_jitter_minutes: int = int(os.getenv("INTERVAL_JITTER_MINUTES", "25"))
    
    # X (Twitter)
    enable_x: bool = os.getenv("ENABLE_X", "false").lower() in ("true", "1", "yes")
    x_use_selenium: bool = os.getenv("X_USE_SELENIUM", "true").lower() in ("true", "1", "yes")
    x_headless: bool = os.getenv("X_HEADLESS", "false").lower() in ("true", "1", "yes")
    x_chrome_profile_dir: str = os.getenv("X_CHROME_PROFILE_DIR", "chrome_profile_x")
    x_attach_image: bool = os.getenv("X_ATTACH_IMAGE", "true").lower() in ("true", "1", "yes")
    # 投稿モード: "thread" (親ポストはURLなし画像付き＋自己リプでURL案内: Xのおすすめ優遇) / "link" (本文にURL直貼り)
    x_post_mode: str = os.getenv("X_POST_MODE", "thread").strip().lower()
    x_account_handle: str = os.getenv("X_ACCOUNT_HANDLE", "").strip()
    x_api_key: str = os.getenv("X_API_KEY", "")
    x_api_secret: str = os.getenv("X_API_SECRET", "")
    x_access_token: str = os.getenv("X_ACCESS_TOKEN", "")
    x_access_secret: str = os.getenv("X_ACCESS_SECRET", "")
    x_bearer_token: str = os.getenv("X_BEARER_TOKEN", "")
    
    # Discord
    enable_discord: bool = os.getenv("ENABLE_DISCORD", "false").lower() in ("true", "1", "yes")
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    # Telegram
    enable_telegram: bool = os.getenv("ENABLE_TELEGRAM", "false").lower() in ("true", "1", "yes")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Bluesky
    enable_bluesky: bool = os.getenv("ENABLE_BLUESKY", "false").lower() in ("true", "1", "yes")
    bluesky_handle: str = os.getenv("BLUESKY_HANDLE", "")
    bluesky_app_password: str = os.getenv("BLUESKY_APP_PASSWORD", "")

    # 特価まとめWebサイト (中継・クッションサイト生成設定)
    enable_site_generation: bool = os.getenv("ENABLE_SITE_GENERATION", "true").lower() in ("true", "1", "yes")
    site_title: str = os.getenv("SITE_TITLE", "特価速報ナビ｜Amazonタイムセール・大特価まとめ")
    site_base_url: str = os.getenv("SITE_BASE_URL", "").rstrip("/")
    auto_git_push: bool = os.getenv("AUTO_GIT_PUSH", "false").lower() in ("true", "1", "yes")
    # サイト掲載の上限件数と、掲載から外すまでの日数 (価格の古さ対策: 鮮度を最優先し3日以内に厳選)
    site_max_items: int = int(os.getenv("SITE_MAX_ITEMS", "100"))
    site_max_age_days: int = int(os.getenv("SITE_MAX_AGE_DAYS", "3"))
    google_site_verification: str = os.getenv("GOOGLE_SITE_VERIFICATION", "").strip()

    # クリック解析 & 自動学習ループ (GAS / Webhook / GA4)
    click_tracker_url: str = os.getenv("CLICK_TRACKER_URL", "").strip()
    ga_measurement_id: str = os.getenv("GA_MEASUREMENT_ID", "").strip()

config = Config()
