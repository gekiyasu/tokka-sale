import time
import logging
import argparse
import schedule
from config import config
from db import Database
from deals_tracker import DealsTracker
from publisher import MultiPublisher

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("AmazonSaleBot")

def run_job(tracker: DealsTracker, db: Database, publisher: MultiPublisher, force: bool = False, limit: int = 3):
    logger.info("🔍 セール商品のスキャンを開始します...")
    deals = tracker.fetch_deals()
    
    if not deals:
        logger.info("該当するセール商品はありませんでした。")
        return

    logger.info(f"{len(deals)}件のセール候補を取得しました。")
    posted_count = 0

    for deal in deals:
        if limit and posted_count >= limit:
            logger.info(f"今回の配信上限（{limit}件）に達したためスキャンを終了します。")
            break

        # 重複チェック（24時間以内に投稿済みの商品はスキップ、force指定時は無視）
        if not force and db.is_recently_posted(deal.asin):
            logger.debug(f"⏭️ ASIN: {deal.asin} は最近投稿済みのためスキップします。")
            continue

        logger.info(f"🚀 新規セール検知: [{deal.discount_percent}% OFF] {deal.title[:30]}...")
        success_count = publisher.broadcast(deal)
        any_enabled = any(getattr(pub, 'enabled', False) for pub in publisher.publishers)
        # Amazonページで実在・割引を確認できた商品は、SNS側の投稿制限(X安全装置など)で見送られても
        # まとめサイトには掲載する (サイトは自動で拡充される)
        live_verified = bool(getattr(deal, "_live_synced", False))
        if any_enabled and success_count == 0 and not live_verified:
            logger.warning(f"⚠️ ASIN: {deal.asin} の配信がスキップされました（次の商品を試行します）。")
            continue

        if not force:
            db.record_post(deal.asin, deal.current_price, deal.discount_percent, deal.title, deal=deal)
        posted_count += 1
        
        # 連続投稿によるスパム・レート制限回避のため十分なインターバルを挟む
        time.sleep(10)

    logger.info(f"スキャン完了: {posted_count}件の新規セールを配信しました。")

def main():
    parser = argparse.ArgumentParser(description="Amazon Sale Affiliate Bot")
    parser.add_argument("--once", action="store_true", help="1回だけスキャンを実行して終了します")
    parser.add_argument("--force", action="store_true", help="過去の投稿履歴を無視してテスト実行します")
    parser.add_argument("--count", type=int, default=1, help="1回のスキャンで投稿する最大件数 (デフォルト: 1件で安全運転)")
    args = parser.parse_args()

    tracker = DealsTracker()
    db = Database()
    publisher = MultiPublisher()

    logger.info("✨ Amazonセール自動検知＆SNS投稿ボットを起動しました。")

    if args.once or args.force:
        run_job(tracker, db, publisher, force=args.force, limit=args.count)
        return

    # 定期実行スケジュール
    interval = config.check_interval_minutes
    schedule.every(interval).minutes.do(run_job, tracker, db, publisher, limit=args.count)
    logger.info(f"⏳ {interval}分ごとに定期スキャン（最大{args.count}件/回）を実行します。(Ctrl+Cで停止)")

    # 初回即時実行
    run_job(tracker, db, publisher, limit=args.count)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
