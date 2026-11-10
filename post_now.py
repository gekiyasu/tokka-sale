"""
今すぐXとBlueskyへ最新セール商品を1件テスト投稿するスクリプト (夜間制限バイパス)
"""
import logging
import time
from config import config
from models import ProductDeal
from deals_tracker import DealsTracker
from site_generator import SiteGenerator
from db import Database
from publisher import XPublisher, BlueskyPublisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PostNow")

def main():
    print("=" * 60)
    print("🚀 X & Blueskyへの同時即時投稿を開始します...")
    print(f"サイトBASE URL: {config.site_base_url}")
    print(f"Bluesky Handle: @{config.bluesky_handle}")
    print("=" * 60)

    db = Database()

    # 前回の投稿から20分間隔を確保
    with db._get_connection() as conn:
        last_str = conn.cursor().execute("SELECT MAX(posted_at) FROM posted_deals").fetchone()[0]
    if last_str:
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        last_dt = datetime.strptime(last_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(JST)
        target_time = last_dt + timedelta(minutes=20)
        now_jst = datetime.now(JST)
        diff = (target_time - now_jst).total_seconds()
        if diff > 0:
            print(f"⏳ 前回の投稿から20分空けるため、あと {int(diff)}秒 待機します (投稿開始予定: {target_time.strftime('%H:%M:%S')})...")
            time.sleep(diff)

    tracker = DealsTracker()
    deals = tracker.fetch_deals()

    target_deal = None
    for deal in deals:
        deal.generate_affiliate_url(config.amazon_tag)
        # 最近投稿済みでない、かつAmazonページと一致するもの
        if db.is_recently_posted(deal.asin):
            continue
        if not tracker.sync_live_amazon_data(deal):
            continue
        target_deal = deal
        break

    if not target_deal:
        for deal in deals:
            deal.generate_affiliate_url(config.amazon_tag)
            if tracker.sync_live_amazon_data(deal):
                target_deal = deal
                break

    if not target_deal:
        print("❌ 有効なセール商品が見つかりませんでした。")
        return

    print(f"📦 投稿対象: {target_deal.title}")
    print(f"💰 価格: ￥{target_deal.regular_price:,} ➜ ￥{target_deal.current_price:,} ({target_deal.discount_percent}% OFF)")
    
    # 1. サイト生成 & GitHub Pages push
    print("🌐 クッションページ＆OGP画像を生成中...")
    gen = SiteGenerator(db)
    gen.build_site(latest_deal=target_deal)

    share_url = target_deal.get_share_url(config.site_base_url)
    print(f"🔗 クッションページURL: {share_url}")

    # 2. Bluesky へ投稿 (API経由)
    print("\n🦋 Bluesky 投稿中...")
    bsky_pub = BlueskyPublisher()
    bsky_ok = False
    if bsky_pub.enabled:
        bsky_ok = bsky_pub.publish(target_deal)
        if bsky_ok:
            print("🎉 Blueskyへの投稿に成功しました！")
            print(f"確認URL: https://bsky.app/profile/{config.bluesky_handle}")
        else:
            print("⚠️ Blueskyへの投稿に失敗しました。")
    else:
        print("⚠️ Blueskyが無効または認証未設定です。")

    # 3. X へ投稿 (Selenium)
    print("\n🐦 X (Selenium) 投稿中...")
    x_pub = XPublisher()
    x_pub.enabled = True
    x_pub.use_selenium = True
    
    # ガードチェックをバイパスして投稿実行
    x_ok = x_pub._publish_via_selenium(target_deal)
    if x_ok:
        print("🎉 X への投稿に成功しました！")
        print("確認URL: https://x.com/tokka_sokuho")
    else:
        print("⚠️ Xへの投稿に失敗しました。")

    if bsky_ok or x_ok:
        db.record_post(target_deal.asin, target_deal.current_price, target_deal.discount_percent, target_deal.title, deal=target_deal)
        print("\n✅ DBに投稿履歴を保存しました。")
        print(f"商品: {target_deal.title}")
        print(f"リンク: {share_url}")
    else:
        print("\n❌ すべてのSNSへの投稿に失敗しました。")

if __name__ == "__main__":
    main()
