"""
テスト専用スクリプト
スパム判定された旧アカウント (@tokkasokuho.bsky.social) に向けて
画像付きリンクカードのテスト投稿を行います。
"""
import logging
from models import ProductDeal
from publisher import BlueskyPublisher
from config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# テスト用アカウント情報
TEST_HANDLE = "tokkasokuho.bsky.social"
TEST_APP_PASSWORD = "xhn5-ogac-gf77-v2sn"

def main():
    print("=" * 60)
    print("🛠️ テスト用アカウントへの画像リンク投稿テストを開始します")
    print(f"送信先: @{TEST_HANDLE}")
    print("=" * 60)

    # 一時的にテスト用アカウントで初期化
    publisher = BlueskyPublisher()
    publisher.enabled = True
    
    # ログイン設定をテスト用に差し替えて認証
    config.bluesky_handle = TEST_HANDLE
    config.bluesky_app_password = TEST_APP_PASSWORD
    if not config.site_base_url:
        config.site_base_url = "http://localhost:8765"
    publisher._login()

    if not publisher.access_jwt:
        print("❌ テスト用アカウントへのログインに失敗しました。")
        return

    # リアルタイム検索＋カタログから取得し、実在＆現在セール中の商品を1件テスト投稿
    from deals_tracker import DealsTracker
    from site_generator import SiteGenerator
    from db import Database
    tracker = DealsTracker()
    db = Database()
    deals = tracker.fetch_deals()

    for deal in deals:
        deal.generate_affiliate_url(config.amazon_tag)
        if not tracker.sync_live_amazon_data(deal):
            continue
        SiteGenerator(db).build_site(latest_deal=deal)
        if publisher.publish(deal):
            db.record_post(deal.asin, deal.current_price, deal.discount_percent, deal.title, deal=deal)
            SiteGenerator(db).build_site(latest_deal=deal)
            print("\n✅ 画像リンク付き投稿に成功しました！")
            print(f"📦 投稿商品名: {deal.title}")
            print(f"💰 価格: ￥{deal.regular_price:,} ➜ ￥{deal.current_price:,} ({deal.discount_percent}% OFF)")
            print(f"🖼️ 使用画像URL: {deal.image_url}")
            print(f"🌐 カードの遷移先(クッションページ): {deal.get_share_url(config.site_base_url)}")
            print(f"🔗 Amazonリンク: {deal.affiliate_url}")
            print(f"確認URL: https://bsky.app/profile/{TEST_HANDLE}")
            return

    print("\n❌ 投稿に失敗しました。ログを確認してください。")

if __name__ == "__main__":
    main()
