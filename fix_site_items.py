"""
既存掲載商品のクリーンアップ (一度きりの修復スクリプト)
- 指定ASIN(リンク切れ確認済み)を削除
- 画像なし/元値なしの商品は Amazon ページを再取得して補完。取得できなければ削除
- docs/ を再生成して push
"""
import logging
import time
from pathlib import Path

from config import config
from db import Database
from deals_tracker import DealsTracker
from models import ProductDeal
from site_generator import SiteGenerator, DEALS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("Cleanup")

FORCE_DELETE = {"B09X1K87B4", "B0BCK7P97B"}  # サーキュレーター / アタックZERO


def delete_asin(db: Database, asin: str):
    with db._get_connection() as conn:
        conn.execute("DELETE FROM posted_deals WHERE asin = ?", (asin,))
        conn.commit()
    page = DEALS_DIR / f"{asin}.html"
    if page.exists():
        page.unlink()


def main():
    db = Database()
    tracker = DealsTracker()

    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT asin, MAX(id), category, COALESCE(image_url,''), COALESCE(regular_price,0) "
            "FROM posted_deals GROUP BY asin"
        ).fetchall()

    fixed = deleted = 0
    for asin, last_id, category, image_url, regular_price in rows:
        if asin in FORCE_DELETE:
            delete_asin(db, asin)
            deleted += 1
            logger.info(f"削除(指定): {asin}")
            continue
        if image_url and regular_price > 0:
            continue

        deal = ProductDeal(
            asin=asin, title="Amazon注目セール商品", current_price=1000, regular_price=1500,
            discount_percent=20, image_url="", rating=4.0, reviews_count=0,
            category=category or "注目セール", highlight="",
        )
        deal._expected_keyword = ""
        deal.generate_affiliate_url(config.amazon_tag)
        time.sleep(2)
        if tracker.sync_live_amazon_data(deal) and deal.image_url:
            with db._get_connection() as conn:
                conn.execute(
                    "UPDATE posted_deals SET title=?, price=?, regular_price=?, discount_percent=?, "
                    "image_url=?, rating=?, reviews_count=?, affiliate_url=? WHERE asin=?",
                    (deal.title, deal.current_price, deal.regular_price, deal.discount_percent,
                     deal.image_url, deal.rating, deal.reviews_count, deal.affiliate_url, asin),
                )
                conn.commit()
            fixed += 1
            logger.info(f"補完: {asin} {deal.title[:30]}")
        else:
            delete_asin(db, asin)
            deleted += 1
            logger.info(f"削除(取得不可/割引なし): {asin}")

    logger.info(f"補完 {fixed}件 / 削除 {deleted}件")
    SiteGenerator(db).build_site()  # AUTO_GIT_PUSH=true なら push まで実施


if __name__ == "__main__":
    main()
