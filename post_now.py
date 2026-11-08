"""
今すぐXへ最新セール商品を1件テスト投稿するスクリプト (夜間制限バイパス)
"""
import logging
import time
from config import config
from models import ProductDeal
from deals_tracker import DealsTracker
from site_generator import SiteGenerator
from db import Database
from publisher import XPublisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PostNow")

def main():
    print("=" * 60)
    print("🚀 Xへの即時テスト投稿を開始します...")
    print(f"サイトBASE URL: {config.site_base_url}")
    print("=" * 60)

    db = Database()
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
    print("🌐 クッションページを生成中...")
    gen = SiteGenerator(db)
    gen.build_site(latest_deal=target_deal)

    share_url = target_deal.get_share_url(config.site_base_url)
    print(f"🔗 クッションページURL: {share_url}")

    # 2. X へ投稿 (Selenium)
    print("🐦 X (Selenium) 投稿中...")
    pub = XPublisher()
    pub.enabled = True
    pub.use_selenium = True
    
    # ガードチェックをバイパスして投稿実行
    ok = pub._publish_via_selenium(target_deal)
    if ok:
        db.record_post(target_deal.asin, target_deal.current_price, target_deal.discount_percent, target_deal.title, deal=target_deal)
        print("\n🎉 X へのテスト投稿が完了しました！")
        print(f"商品: {target_deal.title}")
        print(f"リンク: {share_url}")
        print("Xのプロフィール (https://x.com/tokka_sokuho) を開いて投稿をご確認ください！")
    else:
        print("\n❌ 投稿に失敗しました。")

if __name__ == "__main__":
    main()
