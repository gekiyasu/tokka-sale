"""
クリックデータ自動同期 ＆ 解析モジュール (Auto PDCA Tracker)

機能:
1. Google Apps Script (GAS) や 独自Webhookエンドポイントから最新のクリックイベントを自動取得し、
   SQLite (deals_history.db) の click_events テーブルへ同期。
2. クリック実績に基づき、各カテゴリのパフォーマンス（CTR・人気度）をスコアリング。
3. 手動インポート（CSV / JSON）にも対応。
"""
import logging
import json
import requests
from pathlib import Path
from typing import List, Dict, Optional
from config import config
from db import Database, CATEGORIES, normalize_category

logger = logging.getLogger(__name__)

class ClickTrackerSync:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.endpoint_url = config.click_tracker_url

    def sync(self) -> int:
        """リモートエンドポイント (GAS等) から最新のクリックログを取得してDBへ反映"""
        if not self.endpoint_url:
            logger.debug("[AnalyticsSync] CLICK_TRACKER_URL が設定されていないためリモート同期をスキップします。")
            return 0

        try:
            logger.info(f"[AnalyticsSync] クリック計測エンドポイントからログを取得中: {self.endpoint_url[:40]}...")
            # エンドポイントにGETリクエストを送信 (GASはリダイレクトするため allow_redirects=True)
            res = requests.get(self.endpoint_url, timeout=15, allow_redirects=True)
            if res.status_code != 200:
                logger.warning(f"[AnalyticsSync] エンドポイントからの応答が異常です (HTTP {res.status_code})")
                return 0

            data = res.json()
            events = data.get("clicks", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if not events:
                logger.debug("[AnalyticsSync] 新しい未同期クリックイベントはありませんでした。")
                return 0

            inserted = self.db.record_clicks_batch(events)
            if inserted > 0:
                logger.info(f"✅ [AnalyticsSync] 新規クリックログ {inserted} 件を学習DBへ同期しました！")
            return inserted

        except requests.exceptions.RequestException as e:
            logger.warning(f"[AnalyticsSync] リモート同期通信エラー: {e}")
            return 0
        except json.JSONDecodeError as e:
            logger.warning(f"[AnalyticsSync] レスポンスのJSONパースに失敗しました: {e}")
            return 0
        except Exception as e:
            logger.error(f"[AnalyticsSync] クリック同期処理中に予期せぬエラー: {e}")
            return 0

    def import_local_file(self, file_path: Path) -> int:
        """ローカルの JSON / CSV ログファイルからクリックデータを手動インポート"""
        if not file_path.exists():
            return 0
        try:
            if file_path.suffix.lower() == ".json":
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                events = data if isinstance(data, list) else data.get("clicks", [])
                return self.db.record_clicks_batch(events)
            elif file_path.suffix.lower() == ".csv":
                import csv
                events = []
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        events.append(row)
                return self.db.record_clicks_batch(events)
        except Exception as e:
            logger.error(f"[AnalyticsSync] ローカルファイル取り込みエラー: {e}")
        return 0

    def print_analytics_summary(self, days: int = 7) -> None:
        """直近のカテゴリ別クリック数と人気商品のサマリーをコンソール出力"""
        stats = self.db.get_category_click_stats(days=days)
        total_clicks = sum(stats.values())
        top_asins = self.db.get_top_clicked_asins(days=days, limit=5)

        logger.info(f"📊 【過去{days}日間のクリック解析レポート】 合計: {total_clicks} クリック")
        for cat, cnt in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            pct = (cnt / total_clicks * 100) if total_clicks > 0 else 0
            bar = "■" * int(pct // 10)
            logger.info(f"  - {cat.ljust(10)}: {cnt:3d} 回 ({pct:5.1f}%) {bar}")

        if top_asins:
            logger.info("🔥 【クリック上位商品トップ5】")
            for idx, item in enumerate(top_asins, 1):
                logger.info(f"  {idx}. [{item['category']}] {item['title'][:32]}... ({item['clicks']}クリック)")
