import random
from dataclasses import dataclass
from typing import Optional

@dataclass
class ProductDeal:
    asin: str
    title: str
    current_price: int
    regular_price: int
    discount_percent: int
    image_url: str
    rating: float
    reviews_count: int
    category: str
    highlight: str = ""
    affiliate_url: str = ""

    def __post_init__(self):
        # 確実に表示できるAmazon公式高解像度CDN画像をフォールバック設定
        if not self.image_url or "images-na" not in self.image_url:
            self.image_url = f"https://images-na.ssl-images-amazon.com/images/P/{self.asin}.01._SCLZZZZZZZ_.jpg"

    def generate_affiliate_url(self, tag: str) -> str:
        # Amazonの公式トラッキングリンク形式
        self.affiliate_url = f"https://www.amazon.co.jp/dp/{self.asin}?tag={tag}"
        return self.affiliate_url

    def get_share_url(self, site_base_url: str = "") -> str:
        """中継サイト(SITE_BASE_URL)が設定されていれば個別クッションページURLを返し、未設定時はAmazon直リンクを返す"""
        base = (site_base_url or "").strip().rstrip("/")
        if base:
            return f"{base}/deals/{self.asin}.html"
        return self.affiliate_url

    def format_post_text(self, max_length: Optional[int] = 280) -> str:
        """シンプルで視認性の高い投稿文を生成"""
        title_summary = self.title
        for clutter in ["【2023年秋発売】", "【Amazon.co.jp限定】", "【新型】"]:
            title_summary = title_summary.replace(clutter, "").strip()

        tag_pools = [
            "#Amazonセール #PR",
            "#Amazonタイムセール #PR",
            "#Amazon特売 #お得情報 #PR",
            "#タイムセール速報 #Amazon #PR",
        ]
        chosen_tags = random.choice(tag_pools)

        full_text = (
            f"{title_summary}\n\n"
            f"{self.discount_percent}%OFF🉐\n"
            f"￥{self.regular_price:,}➡️￥{self.current_price:,}\n\n"
            f"{chosen_tags}"
        )

        if max_length and len(full_text) > max_length:
            excess = len(full_text) - max_length
            title_summary = title_summary[:max(15, len(title_summary) - excess - 3)] + "..."
            full_text = (
                f"{title_summary}\n\n"
                f"{self.discount_percent}%OFF🉐\n"
                f"￥{self.regular_price:,}➡️￥{self.current_price:,}\n\n"
                f"{chosen_tags}"
            )
        return full_text

    def format_x_post_text(self, share_url: str = "") -> str:
        """X (旧Twitter) 用のリンク付き投稿文を生成 (140文字制限対応)"""
        title_summary = self.title
        for clutter in ["【2023年秋発売】", "【Amazon.co.jp限定】", "【新型】"]:
            title_summary = title_summary.replace(clutter, "").strip()

        tag_pools = [
            "#Amazonセール #PR",
            "#Amazonタイムセール #PR",
            "#Amazon特売 #お得情報 #PR",
            "#タイムセール速報 #Amazon #PR",
        ]
        chosen_tags = random.choice(tag_pools)

        if len(title_summary) > 55:
            title_summary = title_summary[:52] + "..."

        target_url = share_url or self.affiliate_url

        return (
            f"{title_summary}\n\n"
            f"🔥{self.discount_percent}%OFF🉐\n"
            f"￥{self.regular_price:,}➡️￥{self.current_price:,}\n"
            f"👇特価詳細・セール一覧\n"
            f"{target_url}\n\n"
            f"{chosen_tags}"
        )
