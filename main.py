import time
import random
import logging
import argparse
from datetime import datetime, timedelta, timezone
from config import config
from db import Database
from deals_tracker import DealsTracker
from publisher import MultiPublisher

JST = timezone(timedelta(hours=9))

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("AmazonSaleBot")

def run_job(tracker: DealsTracker, db: Database, publisher: MultiPublisher, force: bool = False, limit: int = 3) -> int:
    logger.info("🔍 セール商品のスキャンを開始します...")
    deals = tracker.fetch_deals()
    
    if not deals:
        logger.info("該当するセール商品はありませんでした。")
        return 0

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
    return posted_count

def calculate_next_wait_seconds(posted: bool) -> tuple[int, datetime]:
    """
    次回巡回までの待機秒数と次回予定時刻(JST)を算出。
    毎回ランダムな揺らぎ（Jitter）を持たせ、機械的な定時投稿を回避します。
    - 投稿成功時 / 通常時: 基準(例:120分) ± 揺らぎ(例:25分) + 秒揺らぎ (例: 1時間47分, 2時間7分 等)
    - 候補なし時: 新着を逃さないよう短め (20〜35分)
    - 夜間(23:00〜8:00 JST): アカウント保護のため明朝8時台まで休止待機
    """
    now_jst = datetime.now(JST)

    # 1. 夜間休止判定 (23:00〜翌朝8:00)
    if now_jst.hour >= 23 or now_jst.hour < 8:
        if now_jst.hour >= 23:
            target_date = (now_jst + timedelta(days=1)).date()
        else:
            target_date = now_jst.date()
        # 翌朝 8:05 〜 8:30 のランダムな時刻に再開
        target_time = datetime(target_date.year, target_date.month, target_date.day, 8, 0, 0, tzinfo=JST)
        target_time += timedelta(minutes=random.randint(5, 30), seconds=random.randint(0, 59))
        wait_seconds = max(60, int((target_time - now_jst).total_seconds()))
        return wait_seconds, target_time

    # 2. 日中の間隔計算
    base_min = config.check_interval_minutes
    jitter_min = config.interval_jitter_minutes

    if posted:
        # 投稿があった場合: 基準値 ± 揺らぎ幅 + 秒単位の揺らぎ
        min_min = max(30, base_min - jitter_min)
        max_min = max(min_min + 5, base_min + jitter_min)
        rand_min = random.randint(min_min, max_min)
    else:
        # 投稿がなかった場合: 短めの揺らぎで新着をチェック
        rand_min = random.randint(20, 35)

    rand_sec = random.randint(0, 59)
    wait_seconds = rand_min * 60 + rand_sec
    target_time = now_jst + timedelta(seconds=wait_seconds)

    # もし次回予定が夜間に入ってしまう場合は、明朝8時台にシフト
    if target_time.hour >= 23:
        target_date = (now_jst + timedelta(days=1)).date()
        target_time = datetime(target_date.year, target_date.month, target_date.day, 8, 0, 0, tzinfo=JST)
        target_time += timedelta(minutes=random.randint(5, 30), seconds=random.randint(0, 59))
        wait_seconds = max(60, int((target_time - now_jst).total_seconds()))

    return wait_seconds, target_time

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

    logger.info(f"⏳ 巡回間隔: 基準{config.check_interval_minutes}分 (±{config.interval_jitter_minutes}分のランダム揺らぎ付き) で常駐監視を開始します。(Ctrl+Cで停止)")

    while True:
        try:
            posted_count = run_job(tracker, db, publisher, limit=args.count)
        except Exception as e:
            logger.error(f"❌ スキャン実行中に予期せぬエラーが発生しました: {e}", exc_info=True)
            posted_count = 0

        # 次回待機時間の計算（毎回ランダムに変動）
        wait_seconds, next_time = calculate_next_wait_seconds(posted=bool(posted_count > 0))
        hours = wait_seconds // 3600
        mins = (wait_seconds % 3600) // 60
        secs = wait_seconds % 60
        time_str = f"{hours}時間{mins}分{secs}秒" if hours > 0 else f"{mins}分{secs}秒"

        logger.info(f"☕ 待機中... 次回巡回予定: {next_time.strftime('%Y-%m-%d %H:%M:%S')} (約{time_str}後)")

        # 安全なスリープ（Ctrl+Cですぐ停止できるように細かく待機）
        remaining = wait_seconds
        while remaining > 0:
            step = min(remaining, 5)
            time.sleep(step)
            remaining -= step

if __name__ == "__main__":
    main()
