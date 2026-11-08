import sqlite3
from pathlib import Path
from typing import List, Optional
from models import ProductDeal
from config import config

DB_PATH = Path(__file__).parent / "deals_history.db"

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
        category = deal.category if deal else "注目セール"
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
            cat = r["category"] or "注目セール"
            # タイトルからカテゴリを簡易推定（過去データ補完用）
            if cat == "注目セール":
                if any(k in title for k in ["コーラ", "水", "お茶", "レッドブル", "飲料", "ラベルレス", "ビール", "コーヒー"]):
                    cat = "飲料・食品"
                elif any(k in title for k in ["Anker", "モバイルバッテリー", "充電器", "イヤホン", "ケーブル", "Philips", "UGREEN", "CIO"]):
                    cat = "ガジェット"
                elif any(k in title for k in ["マウス", "SSD", "バッファロー", "ロジクール", "エレコム", "キーボード", "モニター"]):
                    cat = "PC・周辺機器"
                elif any(k in title for k in ["アイリス", "冷蔵庫", "洗濯機", "掃除機", "電子レンジ", "家電"]):
                    cat = "家電・日用品"

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
