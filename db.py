import sqlite3
from pathlib import Path
from typing import List, Optional
from models import ProductDeal
from config import config

DB_PATH = Path(__file__).parent / "deals_history.db"

# サイト表示用の統一カテゴリ (これ以外の表記ゆれは normalize_category で寄せる)
CATEGORIES = ["ガジェット", "PC・周辺機器", "家電", "キッチン", "食品・飲料", "日用品", "その他"]

_CATEGORY_ALIASES = {
    "ガジェット": "ガジェット", "オーディオ": "ガジェット",
    "PC周辺機器": "PC・周辺機器", "PC・周辺機器": "PC・周辺機器",
    "PC・スマホ周辺機器": "PC・周辺機器", "ストレージ": "PC・周辺機器",
    "家電": "家電",
    "キッチン": "キッチン",
    "食品・飲料": "食品・飲料", "飲料・食品": "食品・飲料", "飲料・食品・": "食品・飲料",
    "日用品": "日用品", "ホーム": "日用品",
}

_KEYWORDS = [  # 上から順に判定 (曖昧なカテゴリ名・未分類のときにタイトルから推定)
    ("食品・飲料", ["コーラ", "炭酸水", "天然水", "ミネラルウォーター", "お茶", "麦茶", "レッドブル", "飲料", "ラベルレス",
                "ビール", "コーヒー", "珈琲", "プロテイン", "ご飯", "カップ麺", "ラーメン", "お菓子", "ドリップ", "ジュース", "水 "]),
    ("PC・周辺機器", ["マウス", "SSD", "キーボード", "モニター", "USBハブ", "USB-C ハブ", "ハブ", "フラッシュメモリ", "microSD", "SDカード", "HDD", "Logicool", "ロジクール"]),
    ("ガジェット", ["モバイルバッテリー", "充電器", "イヤホン", "ヘッドホン", "ケーブル", "スマートウォッチ", "Fire TV", "Anker", "UGREEN", "Bluetooth", "ポータブル電源", "乾電池", "電池", "スマホ"]),
    ("キッチン", ["フライパン", "保存容器", "鍋", "弁当", "包丁", "まな板", "食器", "ケトル", "食パン袋", "密閉"]),
    ("日用品", ["洗剤", "シャンプー", "ボディソープ", "ハンドソープ", "ティッシュ", "トイレット", "歯磨き", "マウスウォッシュ", "マスク", "ゴミ袋", "ブラシ", "柔軟剤", "詰替", "詰め替え"]),
    ("家電", ["冷蔵庫", "洗濯機", "掃除機", "電子レンジ", "空気清浄機", "サーキュレーター", "アイロン", "炊飯器", "ドライヤー", "家電", "エアコン", "扇風機"]),
]


def normalize_category(raw: Optional[str], title: str = "") -> str:
    """カテゴリの表記ゆれを統一カテゴリ(CATEGORIES)へ寄せる。
    既知の表記はそのまま変換し、複合・未分類の表記(例: 家電・日用品, 注目セール)はタイトルから推定する。"""
    raw = (raw or "").strip()
    if raw in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[raw]
    for cat, words in _KEYWORDS:
        if any(w in title for w in words):
            return cat
    return "その他"

class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posted_deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asin TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    discount_percent INTEGER NOT NULL,
                    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    title TEXT,
                    regular_price INTEGER DEFAULT 0,
                    image_url TEXT DEFAULT '',
                    rating REAL DEFAULT 4.2,
                    reviews_count INTEGER DEFAULT 100,
                    category TEXT DEFAULT '注目セール',
                    affiliate_url TEXT DEFAULT ''
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_asin ON posted_deals (asin);")

            # クリックイベント解析・学習用テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS click_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asin TEXT NOT NULL,
                    category TEXT DEFAULT 'その他',
                    button_type TEXT DEFAULT 'main_button',
                    price INTEGER DEFAULT 0,
                    discount_percent INTEGER DEFAULT 0,
                    clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    referrer TEXT DEFAULT ''
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_click_asin ON click_events (asin);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_click_cat ON click_events (category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_click_time ON click_events (clicked_at);")

            # 既存DBへのカラム自動マイグレーション
            cursor.execute("PRAGMA table_info(posted_deals)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            migrations = [
                ("regular_price", "INTEGER DEFAULT 0"),
                ("image_url", "TEXT DEFAULT ''"),
                ("rating", "REAL DEFAULT 4.2"),
                ("reviews_count", "INTEGER DEFAULT 100"),
                ("category", "TEXT DEFAULT '注目セール'"),
                ("affiliate_url", "TEXT DEFAULT ''"),
            ]
            for col_name, col_def in migrations:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE posted_deals ADD COLUMN {col_name} {col_def}")

            conn.commit()

    def is_recently_posted(self, asin: str, hours_limit: int = 24) -> bool:
        """指定時間内にすでに投稿済みかどうかを判定"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM posted_deals 
                WHERE asin = ? 
                AND posted_at >= datetime('now', ?)
            """, (asin, f"-{hours_limit} hours"))
            return cursor.fetchone() is not None

    def record_post(
        self,
        asin: str,
        price: int,
        discount_percent: int,
        title: str,
        deal: Optional[ProductDeal] = None
    ):
        """投稿完了した商品を履歴に保存（Webサイト生成用の詳細情報も保存）"""
        regular_price = deal.regular_price if deal else int(round(price / max(0.05, 1.0 - discount_percent / 100.0)))
        image_url = deal.image_url if deal else f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"
        rating = deal.rating if deal else 4.2
        reviews_count = deal.reviews_count if deal else 100
        category = normalize_category(deal.category if deal else "", title)
        affiliate_url = (
            deal.affiliate_url
            if (deal and deal.affiliate_url)
            else f"https://www.amazon.co.jp/dp/{asin}?tag={config.amazon_tag}"
        )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO posted_deals (
                    asin, price, discount_percent, title,
                    regular_price, image_url, rating, reviews_count, category, affiliate_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                asin, price, discount_percent, title,
                regular_price, image_url, rating, reviews_count, category, affiliate_url
            ))
            conn.commit()

    def get_recent_deals(self, limit: int = 200, max_age_days: Optional[int] = None) -> List[dict]:
        """まとめサイト掲載用に直近のセール商品を新しい順（ASIN重複排除）で取得。
        max_age_days を指定すると、掲載(取得)から指定日数を超えた古い商品は除外する（価格の古さ対策）。"""
        age_clause = ""
        params: list = []
        if max_age_days:
            age_clause = "AND posted_at >= datetime('now', ?)"
            params.append(f"-{int(max_age_days)} days")
        params.append(limit)
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT
                    asin,
                    price,
                    discount_percent,
                    posted_at,
                    title,
                    regular_price,
                    image_url,
                    rating,
                    reviews_count,
                    category,
                    affiliate_url
                FROM posted_deals
                WHERE id IN (
                    SELECT MAX(id) FROM posted_deals GROUP BY asin
                )
                {age_clause}
                ORDER BY posted_at DESC, id DESC
                LIMIT ?
            """, params)
            rows = cursor.fetchall()

        results = []
        for r in rows:
            asin = r["asin"]
            price = int(r["price"] or 0)
            disc = int(r["discount_percent"] or 0)
            reg_price = int(r["regular_price"] or 0)
            if reg_price <= price and disc > 0:
                reg_price = int(round(price / max(0.05, 1.0 - disc / 100.0)))
            img = r["image_url"] or f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"
            aff_url = r["affiliate_url"] or f"https://www.amazon.co.jp/dp/{asin}?tag={config.amazon_tag}"
            title = r["title"] or f"Amazon 特価商品 ({asin})"
            cat = normalize_category(r["category"], title)

            results.append({
                "asin": asin,
                "title": title,
                "current_price": price,
                "regular_price": reg_price,
                "discount_percent": disc,
                "image_url": img,
                "rating": float(r["rating"] or 4.2),
                "reviews_count": int(r["reviews_count"] or 100),
                "category": cat,
                "affiliate_url": aff_url,
                "posted_at": r["posted_at"] or "",
            })
        return results

    def record_click(
        self,
        asin: str,
        category: str = "",
        button_type: str = "main_button",
        price: int = 0,
        discount_percent: int = 0,
        referrer: str = "",
        clicked_at: Optional[str] = None
    ) -> None:
        """単一のクリックイベントを記録"""
        cat = normalize_category(category)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if clicked_at:
                cursor.execute("""
                    INSERT INTO click_events (asin, category, button_type, price, discount_percent, referrer, clicked_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (asin, cat, button_type, price, discount_percent, referrer, clicked_at))
            else:
                cursor.execute("""
                    INSERT INTO click_events (asin, category, button_type, price, discount_percent, referrer)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (asin, cat, button_type, price, discount_percent, referrer))
            conn.commit()

    def record_clicks_batch(self, events: List[dict]) -> int:
        """GAS等のエンドポイントから受信した複数のクリックイベントを一括登録 (重複防止付き)"""
        if not events:
            return 0
        inserted = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for ev in events:
                asin = str(ev.get("asin", "")).strip()
                if not asin:
                    continue
                cat = normalize_category(ev.get("category", ""))
                btn = str(ev.get("btn", ev.get("button_type", "main_button")))
                price = int(ev.get("price", 0) or 0)
                disc = int(ev.get("discount", ev.get("discount_percent", 0)) or 0)
                ref = str(ev.get("referrer", ""))[:255]
                ts = ev.get("timestamp") or ev.get("clicked_at")

                # 直近同一タイムスタンプまたは秒単位の重複挿入を回避
                cursor.execute("""
                    SELECT id FROM click_events
                    WHERE asin = ? AND button_type = ? AND clicked_at >= datetime('now', '-5 seconds')
                """, (asin, btn))
                if cursor.fetchone() is not None:
                    continue

                if ts and isinstance(ts, str) and len(ts) >= 19:
                    cursor.execute("""
                        INSERT INTO click_events (asin, category, button_type, price, discount_percent, referrer, clicked_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (asin, cat, btn, price, disc, ref, ts[:19]))
                else:
                    cursor.execute("""
                        INSERT INTO click_events (asin, category, button_type, price, discount_percent, referrer)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (asin, cat, btn, price, disc, ref))
                inserted += 1
            conn.commit()
        return inserted

    def get_category_click_stats(self, days: int = 7) -> dict:
        """指定期間内のカテゴリ別クリック数を集計 (学習アルゴリズム用)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, COUNT(*) as click_cnt
                FROM click_events
                WHERE clicked_at >= datetime('now', ?)
                GROUP BY category
            """, (f"-{days} days",))
            rows = cursor.fetchall()

        stats = {cat: 0 for cat in CATEGORIES}
        for cat, cnt in rows:
            clean_cat = normalize_category(cat)
            stats[clean_cat] = stats.get(clean_cat, 0) + cnt
        return stats

    def get_top_clicked_asins(self, days: int = 7, limit: int = 10) -> List[dict]:
        """直近で最もクリックされている人気ASINトップリスト"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.asin, c.category, COUNT(*) as clicks, MAX(c.clicked_at) as last_clicked,
                       COALESCE(p.title, '') as title, COALESCE(p.price, 0) as price
                FROM click_events c
                LEFT JOIN posted_deals p ON c.asin = p.asin
                WHERE c.clicked_at >= datetime('now', ?)
                GROUP BY c.asin
                ORDER BY clicks DESC
                LIMIT ?
            """, (f"-{days} days", limit))
            return [dict(r) for r in cursor.fetchall()]
