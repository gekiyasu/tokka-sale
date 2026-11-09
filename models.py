import random
from dataclasses import dataclass
from typing import Optional

def _x_weighted_length(text: str) -> int:
    """Xの文字数カウント: URLは一律23、半角(英数・記号)は1、全角・絵文字等は2"""
    import re
    url_re = re.compile(r"https?://\S+")
    total = 23 * len(url_re.findall(text))
    rest = url_re.sub("", text)
    for ch in rest:
        o = ord(ch)
        total += 1 if (o <= 0x10FF or 0x2000 <= o <= 0x200D or 0x2010 <= o <= 0x201F or 0x2032 <= o <= 0x2037) else 2
    return total


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

        target_url = share_url or self.affiliate_url

        # 毎回同じ文面だと「重複・スパム」と判定されやすいため、複数テンプレートをランダムに使い分ける
        templates = [
            "{title}\n\n🔥{d}%OFF🉐\n￥{reg}➡️￥{cur}\n👇特価詳細・セール一覧\n{url}\n\n{tags}",
            "【特価】{title}\n\n￥{cur}（通常￥{reg} / {d}%OFF）\n詳細はこちら👇\n{url}\n\n{tags}",
            "{title}\n\n💰￥{cur}\n（参考価格￥{reg}から{d}%OFF）\n{url}\n\n{tags}",
            "本日のお得情報✨\n{title}\n\n{d}%OFFの￥{cur}\n{url}\n\n{tags}",
        ]
        template = random.choice(templates)

        def build(title: str) -> str:
            return template.format(
                title=title, d=self.discount_percent,
                reg=f"{self.regular_price:,}", cur=f"{self.current_price:,}",
                url=target_url, tags=chosen_tags,
            )

        text = build(title_summary)
        # Xの重み付き文字数 (上限280) を超える場合のみ、単語の区切りで自然に短縮する
        if _x_weighted_length(text) > 280:
            title = title_summary
            while len(title) > 15:
                title = title[:-1]
                # 区切り (スペース・括弧・記号) の直後まで戻して単語途中の切断を避ける
                cut = max(title.rfind(" "), title.rfind("　"), title.rfind("/"), title.rfind("、"))
                candidate = (title[:cut].rstrip() if cut >= 15 else title) + "…"
                if _x_weighted_length(build(candidate)) <= 280:
                    return build(candidate)
                if cut >= 15:
                    title = title[:cut]
            text = build(title[:15] + "…")
        return text
