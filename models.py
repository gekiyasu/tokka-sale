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
            "#Amazonセール #タイムセール",
            "#Amazon特売 #お得情報",
            "#タイムセール速報 #Amazon",
            "#Amazonセール",
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
        """X (旧Twitter) 用のリンク付き投稿文を生成 (140文字制限対応 & #PR明記)"""
        title_summary = self.title
        for clutter in ["【2023年秋発売】", "【Amazon.co.jp限定】", "【新型】"]:
            title_summary = title_summary.replace(clutter, "").strip()

        tag_pools = [
            "#Amazonセール #タイムセール #PR",
            "#Amazonタイムセール #特売情報 #PR",
            "#セール速報 #Amazon #PR",
            "#Amazonお得情報 #タイムセール #PR",
        ]
        chosen_tags = random.choice(tag_pools)

        target_url = share_url or self.affiliate_url
        savings = max(0, self.regular_price - self.current_price)

        # 割引率や評価に応じたキャッチコピー
        badge = "🔥【超目玉】" if self.discount_percent >= 40 else "⚡【タイムセール特価】"
        if self.rating >= 4.3 and self.reviews_count >= 50:
            badge = "⭐【高評価★{:.1f}】".format(self.rating)

        templates = [
            "{badge}{d}%OFF！￥{reg} ➡️ ￥{cur}\n（￥{sav}値引き中）\n{title}\n\n売り切れ前にチェック👇\n{url}\n\n{tags}",
            "【急な値下げ速報】\n{title}\n\n通常 ￥{reg} が【{d}%OFF】の ￥{cur} に急降下！\n詳細・在庫はこちら👇\n{url}\n\n{tags}",
            "本日のお得商品✨\n{title}\n\n💰 ￥{cur}（参考￥{reg}から{d}%OFF / ￥{sav}お得）\nセール会場はこちら👇\n{url}\n\n{tags}",
            "{badge}大幅プライスダウン！\n{title}\n\n🔥{d}%OFFで￥{cur}（通常￥{reg}）\n今すぐチェック👇\n{url}\n\n{tags}",
        ]
        template = random.choice(templates)

        def build(title: str) -> str:
            return template.format(
                badge=badge, title=title, d=self.discount_percent,
                reg=f"{self.regular_price:,}", cur=f"{self.current_price:,}",
                sav=f"{savings:,}",
                url=target_url, tags=chosen_tags,
            )

        text = build(title_summary)
        if _x_weighted_length(text) > 280:
            title = title_summary
            while len(title) > 15:
                title = title[:-1]
                cut = max(title.rfind(" "), title.rfind("　"), title.rfind("/"), title.rfind("、"))
                candidate = (title[:cut].rstrip() if cut >= 15 else title) + "…"
                if _x_weighted_length(build(candidate)) <= 280:
                    return build(candidate)
                if cut >= 15:
                    title = title[:cut]
            text = build(title[:15] + "…")
        return text

    def format_x_thread_parent_text(self) -> str:
        """Xツリー投稿の親ポスト用テキスト (URLを含めないことでXのアルゴリズム優遇を最大化)"""
        title_summary = self.title
        for clutter in ["【2023年秋発売】", "【Amazon.co.jp限定】", "【新型】"]:
            title_summary = title_summary.replace(clutter, "").strip()

        tag_pools = [
            "#Amazonセール #タイムセール #PR",
            "#Amazonタイムセール #特売情報 #PR",
            "#セール速報 #Amazon #PR",
            "#Amazonお得情報 #タイムセール #PR",
        ]
        chosen_tags = random.choice(tag_pools)
        savings = max(0, self.regular_price - self.current_price)

        badge = "🔥【超目玉特価】" if self.discount_percent >= 40 else "⚡【急な値下げ速報】"
        if self.rating >= 4.3 and self.reviews_count >= 50:
            badge = f"⭐【評価★{self.rating:.1f}の人気商品】"

        templates = [
            "{badge}\n通常 ￥{reg} ➡️ 【{d}%OFF】￥{cur}！\n（￥{sav}おトク）\n\n{title}\n\n👇 セール詳細・在庫リンクはリプ欄へ\n\n{tags}",
            "【急なタイムセール値下げ】\n{title}\n\n💰 参考価格: ￥{reg}\n🔥 セール特価: ￥{cur} ({d}% OFF / ￥{sav}引き)\n\n👇 セール会場・在庫確認はリプライ欄から\n\n{tags}",
            "{badge}\n{title}\n\nなんと【{d}%OFF】の ￥{cur} に値下げ中！\n通常より ￥{sav} 安く買えます✨\n\n👇 購入・在庫チェックはリプ欄へ\n\n{tags}",
        ]
        template = random.choice(templates)

        def build(title: str) -> str:
            return template.format(
                badge=badge, title=title, d=self.discount_percent,
                reg=f"{self.regular_price:,}", cur=f"{self.current_price:,}",
                sav=f"{savings:,}",
                tags=chosen_tags,
            )

        text = build(title_summary)
        if _x_weighted_length(text) > 280:
            title = title_summary
            while len(title) > 15:
                title = title[:-1]
                cut = max(title.rfind(" "), title.rfind("　"), title.rfind("/"), title.rfind("、"))
                candidate = (title[:cut].rstrip() if cut >= 15 else title) + "…"
                if _x_weighted_length(build(candidate)) <= 280:
                    return build(candidate)
                if cut >= 15:
                    title = title[:cut]
            text = build(title[:15] + "…")
        return text

    def format_x_thread_reply_text(self, share_url: str = "") -> str:
        """Xツリー投稿の子ポスト(自己リプライ)用テキスト (リンクとセール終了注意喚起)"""
        target_url = share_url or self.affiliate_url
        savings = max(0, self.regular_price - self.current_price)
        return (
            f"🛒 セール会場・在庫確認はこちら👇\n"
            f"{target_url}\n\n"
            f"💡 今なら ￥{savings:,} お得（{self.discount_percent}% OFF）！\n"
            f"※タイムセール特価のため売り切れ・価格変動にご注意ください。"
        )
