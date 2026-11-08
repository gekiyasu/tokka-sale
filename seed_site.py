"""
まとめサイト掲載商品の拡充スクリプト (X等へは投稿しない)

Amazon.co.jp の売れ筋ランキング・検索結果からASINを集め、
商品ページで「現在割引表示あり」を確認できたものだけをDBに登録し、サイトを再生成する。

使い方:
    python seed_site.py                 # 登録のみ (サイトはローカル生成、git pushしない)
    python seed_site.py --count 30      # 目標件数を指定 (デフォルト30)
    python seed_site.py --publish       # 生成後に GitHub Pages へ push (AUTO_GIT_PUSH設定に従う)
"""
import argparse
import logging
import random
import re
import time

import requests

from config import config
from db import Database
from deals_tracker import DealsTracker
from models import ProductDeal
from site_generator import SiteGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("SeedSite")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# (カテゴリ名, 売れ筋ランキングURL)
BESTSELLER_SOURCES = [
    ("ガジェット", "https://www.amazon.co.jp/gp/bestsellers/electronics"),
    ("PC周辺機器", "https://www.amazon.co.jp/gp/bestsellers/computers"),
    ("家電", "https://www.amazon.co.jp/gp/bestsellers/appliances"),
    ("食品・飲料", "https://www.amazon.co.jp/gp/bestsellers/food-beverage"),
    ("日用品", "https://www.amazon.co.jp/gp/bestsellers/hpc"),
    ("キッチン", "https://www.amazon.co.jp/gp/bestsellers/kitchen"),
    ("ホーム", "https://www.amazon.co.jp/gp/bestsellers/home"),
]

# (カテゴリ名, 検索キーワード)
SEARCH_SOURCES = [
    ("ガジェット", "モバイルバッテリー セール"), ("ガジェット", "USB充電器 セール"),
    ("ガジェット", "ワイヤレスイヤホン セール"), ("ガジェット", "スマートウォッチ セール"),
    ("PC周辺機器", "外付けSSD セール"), ("PC周辺機器", "マウス ワイヤレス セール"),
    ("PC周辺機器", "USBハブ セール"), ("PC周辺機器", "キーボード セール"),
    ("家電", "空気清浄機 セール"), ("家電", "電気ケトル セール"),
    ("家電", "サーキュレーター セール"), ("家電", "掃除機 セール"),
    ("食品・飲料", "ミネラルウォーター 2L 24本"), ("食品・飲料", "コーヒー セール"),
    ("食品・飲料", "プロテイン セール"), ("食品・飲料", "カップ麺 まとめ買い"),
    ("日用品", "ティッシュ まとめ買い"), ("日用品", "洗剤 詰め替え セール"),
    ("日用品", "トイレットペーパー セール"), ("日用品", "シャンプー セール"),
    ("キッチン", "フライパン セール"), ("キッチン", "保存容器 セール"),
]


def collect_asins(url: str) -> list:
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            logger.warning(f"取得失敗 {res.status_code}: {url}")
            return []
        found = re.findall(r'(?:data-asin="|/dp/)(B0[A-Z0-9]{8})', res.text)
        return list(dict.fromkeys(found))
    except Exception as e:
        logger.warning(f"収集エラー {url}: {e}")
        return []


def existing_asins(db: Database) -> set:
    with db._get_connection() as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT asin FROM posted_deals").fetchall()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30, help="追加する目標件数")
    parser.add_argument("--publish", action="store_true", help="生成後にgit pushする")
    args = parser.parse_args()

    db = Database()
    tracker = DealsTracker()
    known = existing_asins(db)

    # カテゴリごとに候補を集める
    sources = [(c, u) for c, u in BESTSELLER_SOURCES]
    sources += [(c, f"https://www.amazon.co.jp/s?k={requests.utils.quote(k)}") for c, k in SEARCH_SOURCES]
    random.shuffle(sources)

    candidates = []  # (asin, category)
    seen = set(known)
    for category, url in sources:
        for asin in collect_asins(url)[:12]:
            if asin not in seen:
                seen.add(asin)
                candidates.append((asin, category))
        time.sleep(1.5)
    random.shuffle(candidates)
    logger.info(f"候補ASIN: {len(candidates)}件 (登録済み{len(known)}件は除外)")

    added = 0
    cat_count = {}
    for asin, category in candidates:
        if added >= args.count:
            break
        if cat_count.get(category, 0) >= 6:  # 分野の偏りを抑える
            continue
        deal = ProductDeal(
            asin=asin, title="Amazon注目セール商品", current_price=1000, regular_price=1500,
            discount_percent=20, image_url="", rating=4.0, reviews_count=0,
            category=category, highlight="",
        )
        deal._expected_keyword = ""
        deal.generate_affiliate_url(config.amazon_tag)
        time.sleep(2)
        if not tracker.sync_live_amazon_data(deal):
            continue
        # 品質フィルタ: 割引率・評価・レビュー数
        if deal.discount_percent < 10 or (deal.rating and deal.rating < 3.8) or deal.reviews_count < 10:
            logger.info(f"品質基準未達のためスキップ: {asin}")
            continue

        db.record_post(asin, deal.current_price, deal.discount_percent, deal.title, deal=deal)
        # X投稿の重複判定(24h)に影響しないよう、掲載日時を少し過去にずらす
        offset = random.randint(25, 70)
        with db._get_connection() as conn:
            conn.execute(
                "UPDATE posted_deals SET posted_at = datetime('now', ?) WHERE id = (SELECT MAX(id) FROM posted_deals WHERE asin = ?)",
                (f"-{offset} minutes -25 hours", asin),
            )
            conn.commit()
        cat_count[category] = cat_count.get(category, 0) + 1
        added += 1
        logger.info(f"[{added}/{args.count}] 追加: {category} / {deal.discount_percent}%OFF / {deal.title[:30]}")

    logger.info(f"追加完了: {added}件 {cat_count}")
    if added == 0:
        logger.warning("1件も追加できませんでした。Amazonのブロックの可能性があります。時間をおいて再実行してください。")
        return

    if not args.publish:
        config.auto_git_push = False
    SiteGenerator(db).build_site()
    if not args.publish:
        logger.info("ローカルの docs/ のみ更新しました。内容確認後、--publish か手動pushで公開してください。")


if __name__ == "__main__":
    main()
