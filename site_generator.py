"""
大特価まとめWebサイト（クッションページ / ポータルサイト）自動生成モジュール

機能:
1. SQLite (deals_history.db) に蓄積されたセール商品履歴から、
   スマホ・PC両対応のモダンな「Amazon大特価まとめサイト」を `docs/` フォルダに静的HTML生成します。
   - `docs/index.html`: カテゴリ絞り込み・並び替え（割引率順/新着順/価格順）・検索付きのトップページ
   - `docs/deals/<ASIN>.html`: SNSシェア用OGPタグ（Twitter Large Card対応）付きの個別商品クッションページ
     （上部に該当商品の特大カード＋Amazonボタン、下部に「同時開催中の大特価セール一覧」を表示して回遊率を最大化）
2. `.env` の `AUTO_GIT_PUSH=true` が設定されている場合、生成後に自動で GitHub (GitHub Pages) へ push します。
"""
import argparse
import html
import json
import logging
import subprocess
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

from config import config
from db import Database, normalize_category, CATEGORIES
from models import ProductDeal

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DOCS_DIR = Path(__file__).parent / "docs"
DEALS_DIR = DOCS_DIR / "deals"
OGP_DIR = DOCS_DIR / "ogp"


def _format_jst(utc_str: str) -> str:
    """SQLite の UTC タイムスタンプ文字列を日本時間 (MM/DD HH:MM) に変換"""
    if not utc_str:
        return datetime.now(JST).strftime("%m/%d %H:%M")
    try:
        dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(JST).strftime("%m/%d %H:%M")
    except Exception:
        return utc_str


class SiteGenerator:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.site_title = config.site_title
        self.base_url = config.site_base_url

    def _generate_deal_ogp_image(self, asin: str, image_url: str) -> Optional[Path]:
        """商品画像を 1200x630 (1.91:1) の白背景キャンバス中央に配置し、X/Twitter等のリンクカードで絶対に見切れないOGP画像を生成"""
        if not image_url:
            return None
        target_path = OGP_DIR / f"{asin}.jpg"
        if target_path.exists() and target_path.stat().st_size > 1000:
            return target_path

        try:
            import io
            import requests
            from PIL import Image

            res = requests.get(image_url, timeout=10)
            res.raise_for_status()
            img_bytes = res.content
            if len(img_bytes) < 1000:
                return None

            W, H = 1200, 630
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            prod_img = Image.open(io.BytesIO(img_bytes))

            # 透過・アルファチャンネル処理
            if prod_img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", prod_img.size, (255, 255, 255))
                if prod_img.mode != "RGBA":
                    prod_img = prod_img.convert("RGBA")
                bg.paste(prod_img, mask=prod_img.split()[3])
                prod_img = bg
            else:
                prod_img = prod_img.convert("RGB")

            # X(Twitter)リンクカード (1.91:1〜2:1) およびアプリ内角丸でも上下左右が完全に見切れない安全領域
            # 最大サイズ 900x480 (上下マージン各75px以上、左右マージン各150px以上)
            prod_img.thumbnail((900, 480), Image.Resampling.LANCZOS)
            px = (W - prod_img.width) // 2
            py = (H - prod_img.height) // 2
            canvas.paste(prod_img, (px, py))

            OGP_DIR.mkdir(parents=True, exist_ok=True)
            canvas.save(target_path, format="JPEG", quality=88, optimize=True)
            return target_path
        except Exception as e:
            logger.warning(f"OGP画像の生成をスキップしました (ASIN: {asin}): {e}")
            return None

    def build_site(self, latest_deal: Optional[ProductDeal] = None) -> Path:
        """全ページ (`docs/index.html` および `docs/deals/*.html`) を再生成"""
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        DEALS_DIR.mkdir(parents=True, exist_ok=True)
        OGP_DIR.mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / ".nojekyll").touch(exist_ok=True)

        deals = self.db.get_recent_deals(limit=config.site_max_items, max_age_days=config.site_max_age_days)

        # 今回の新規dealがまだDBに入る前でも先頭に反映されるようにマージ
        if latest_deal:
            latest_dict = {
                "asin": latest_deal.asin,
                "title": latest_deal.title,
                "current_price": latest_deal.current_price,
                "regular_price": latest_deal.regular_price,
                "discount_percent": latest_deal.discount_percent,
                "image_url": latest_deal.image_url,
                "rating": latest_deal.rating,
                "reviews_count": latest_deal.reviews_count,
                "category": normalize_category(latest_deal.category, latest_deal.title),
                "affiliate_url": latest_deal.affiliate_url or latest_deal.generate_affiliate_url(config.amazon_tag),
                "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }
            deals = [ latest_dict ] + [d for d in deals if d["asin"] != latest_deal.asin]
            deals = deals[:config.site_max_items]

        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M")

        # 1. トップページ (docs/index.html) の生成
        index_path = DOCS_DIR / "index.html"
        index_html = self._render_index_html(deals, now_str)
        index_path.write_text(index_html, encoding="utf-8")

        # 2. 各商品の個別クッションページ (docs/deals/<ASIN>.html) の生成
        # 掲載数が多くなるため、毎回全ページを書き直さない (git差分の肥大化防止)。
        # 新規ページ(未生成)と、最新30件のみ更新する。
        for idx, target in enumerate(deals):
            deal_path = DEALS_DIR / f"{target['asin']}.html"
            if deal_path.exists() and idx >= 30:
                continue
            other_deals = [d for d in deals if d["asin"] != target["asin"]][:24]
            deal_html = self._render_deal_page_html(target, other_deals, now_str)
            deal_path.write_text(deal_html, encoding="utf-8")

        logger.info(f"🌐 まとめWebサイトを更新しました: {index_path} (掲載商品数: {len(deals)}件)")

        if config.auto_git_push:
            self._git_push_docs()

        return index_path

    def _git_push_docs(self):
        """GitHub Pages 等への自動デプロイ用 git add / commit / push"""
        repo_dir = Path(__file__).parent
        try:
            subprocess.run(["git", "add", "docs"], cwd=repo_dir, check=True, capture_output=True)
            status = subprocess.run(["git", "status", "--porcelain", "docs"], cwd=repo_dir, capture_output=True, text=True)
            if not status.stdout.strip():
                return
            msg = f"Update sale site ({datetime.now(JST).strftime('%Y-%m-%d %H:%M')})"
            subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True, capture_output=True)
            subprocess.run(["git", "push"], cwd=repo_dir, check=True, capture_output=True, timeout=30)
            logger.info("🚀 GitHub Pages へ最新のセールまとめサイトを自動Pushしました。")
        except Exception as e:
            logger.warning(f"Git自動Pushをスキップしました: {e}")

    def wait_until_live(self, asin: str, timeout: int = 300, interval: int = 15) -> bool:
        """公開サイト上に商品ページ(deals/<ASIN>.html)が表示可能になるまで待つ。
        SNS投稿より先にページが公開されていることを保証し、リンク先が404になるのを防ぐ。"""
        import time
        import requests

        base = (self.base_url or "").rstrip("/")
        if not base:
            return True  # 公開URL未設定(Amazon直リンク運用)なら待機不要
        url = f"{base}/deals/{asin}.html"
        deadline = time.time() + timeout
        while True:
            try:
                res = requests.get(url, timeout=10, headers={"Cache-Control": "no-cache"})
                if res.status_code == 200 and asin in res.text:
                    logger.info(f"✅ 公開ページを確認しました: {url}")
                    return True
            except Exception:
                pass
            if time.time() >= deadline:
                logger.error(f"⚠️ {timeout}秒待っても公開ページが表示されません: {url}")
                return False
            time.sleep(interval)

    def _render_card_html(self, d: dict, is_root: bool = True) -> str:
        asin = html.escape(d["asin"])
        title = html.escape(d["title"])
        price = d["current_price"]
        reg_price = d["regular_price"]
        disc = d["discount_percent"]
        savings = max(0, reg_price - price)
        img = html.escape(d["image_url"])
        cat = html.escape(d["category"])
        aff_url = html.escape(d["affiliate_url"])
        rating = d["rating"]
        reviews = d["reviews_count"]
        time_str = _format_jst(d["posted_at"])
        detail_href = f"deals/{asin}.html" if is_root else f"{asin}.html"
        rakuten_q = html.escape(d["title"][:35])
        rakuten_url = f"https://search.rakuten.co.jp/search/mall/{rakuten_q}/"

        return f"""
        <article class="deal-card" data-category="{cat}" data-discount="{disc}" data-price="{price}" data-savings="{savings}" data-title="{title.lower()}">
          <div class="card-badges">
            <span class="badge-discount">🔥 {disc}% OFF</span>
            <span class="badge-category">{cat}</span>
            <span class="badge-time">🕒 {time_str}</span>
          </div>
          <a href="{aff_url}" target="_blank" rel="nofollow sponsored noopener" class="card-img-link">
            <img src="{img}" alt="{title}" loading="lazy" onerror="this.src='https://m.media-amazon.com/images/G/09/icons/no-img-sm._V192198896_.gif'">
          </a>
          <div class="card-body">
            <h3 class="card-title">
              <a href="{detail_href}">{title}</a>
            </h3>
            <div class="card-rating">
              <span class="stars">⭐ {rating:.1f}</span>
              <span class="reviews">({reviews:,}件のレビュー)</span>
            </div>
            <div class="price-box">
              <div class="price-old">参考価格: <s>￥{reg_price:,}</s></div>
              <div class="price-current">￥{price:,} <span class="tax-in">(税込)</span></div>
              <div class="price-save">💡 ￥{savings:,} お得！</div>
            </div>
            <div class="card-actions">
              <a href="{aff_url}" target="_blank" rel="nofollow sponsored noopener" class="btn-amazon">
                🛒 Amazonで特価を見る
              </a>
              <div class="sub-actions">
                <a href="{detail_href}" class="btn-detail">📄 詳細ページ</a>
                <a href="{rakuten_url}" target="_blank" rel="nofollow noopener" class="btn-rakuten">🔎 楽天で比較</a>
              </div>
            </div>
          </div>
        </article>
        """

    def _common_css(self) -> str:
        return """
        :root {
          --bg: #f4f6f9;
          --card-bg: #ffffff;
          --text: #1a202c;
          --muted: #64748b;
          --amazon: #ff9900;
          --amazon-dark: #e68a00;
          --red: #e11d48;
          --red-light: #ffe4e6;
          --accent: #0f172a;
          --border: #e2e8f0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          font-family: -apple-system, BlinkMacSystemFont, "Hiragino Kaku Gothic ProN", "Noto Sans JP", Meiryo, sans-serif;
          background: var(--bg);
          color: var(--text);
          line-height: 1.55;
        }
        a { color: inherit; text-decoration: none; }
        .site-header {
          background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
          color: #fff;
          position: sticky;
          top: 0;
          z-index: 100;
          box-shadow: 0 2px 12px rgba(0,0,0,0.18);
        }
        .header-inner {
          max-width: 1240px;
          margin: 0 auto;
          padding: 12px 16px;
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 1.25rem;
          font-weight: 800;
          letter-spacing: -0.02em;
        }
        .brand-badge {
          background: var(--red);
          color: #fff;
          font-size: 0.75rem;
          padding: 3px 8px;
          border-radius: 999px;
          font-weight: 700;
        }
        .header-meta {
          font-size: 0.8rem;
          color: #cbd5e1;
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .pr-notice {
          background: rgba(255,255,255,0.12);
          padding: 3px 10px;
          border-radius: 6px;
          font-size: 0.75rem;
        }
        .container {
          max-width: 1240px;
          margin: 0 auto;
          padding: 20px 16px 60px;
        }
        /* コントロールバー（検索・カテゴリ・ソート） */
        .filter-panel {
          background: #fff;
          border-radius: 14px;
          padding: 16px;
          margin-bottom: 22px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.06);
          border: 1px solid var(--border);
        }
        .search-row {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          margin-bottom: 14px;
        }
        .search-input {
          flex: 1;
          min-width: 220px;
          padding: 10px 14px;
          border: 1px solid var(--border);
          border-radius: 10px;
          font-size: 0.95rem;
          outline: none;
        }
        .search-input:focus { border-color: var(--amazon); box-shadow: 0 0 0 3px rgba(255,153,0,0.18); }
        .sort-group {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
        }
        .sort-btn, .cat-btn, .more-btn {
          border: 1px solid var(--border);
          background: #f8fafc;
          color: var(--text);
          padding: 7px 13px;
          border-radius: 999px;
          font-size: 0.84rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.15s;
        }
        .sort-btn:hover, .cat-btn:hover, .more-btn:hover { border-color: #94a3b8; }
        .sort-btn.active {
          background: var(--accent);
          color: #fff;
          border-color: var(--accent);
        }
        .cat-row {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .cat-btn.active {
          background: var(--red);
          color: #fff;
          border-color: var(--red);
        }
        /* 商品グリッド */
        .deals-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(275px, 1fr));
          gap: 18px;
        }
        .deal-card {
          background: var(--card-bg);
          border-radius: 14px;
          border: 1px solid var(--border);
          overflow: hidden;
          display: flex;
          flex-direction: column;
          transition: transform 0.18s ease, box-shadow 0.18s ease;
          box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        }
        .deal-card:hover {
          transform: translateY(-4px);
          box-shadow: 0 12px 24px rgba(0,0,0,0.1);
        }
        .card-badges {
          padding: 10px 12px 0;
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }
        .badge-discount {
          background: var(--red);
          color: #fff;
          font-weight: 800;
          font-size: 0.85rem;
          padding: 3px 10px;
          border-radius: 6px;
        }
        .badge-category {
          background: #f1f5f9;
          color: #334155;
          font-size: 0.75rem;
          font-weight: 600;
          padding: 3px 8px;
          border-radius: 6px;
        }
        .badge-time {
          margin-left: auto;
          font-size: 0.72rem;
          color: var(--muted);
        }
        .card-img-link {
          height: 200px;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 14px;
          background: #fff;
          border-bottom: 1px solid #f1f5f9;
        }
        .card-img-link img {
          max-width: 100%;
          max-height: 100%;
          object-fit: contain;
          transition: transform 0.2s;
        }
        .deal-card:hover .card-img-link img {
          transform: scale(1.04);
        }
        .card-body {
          padding: 14px;
          display: flex;
          flex-direction: column;
          flex: 1;
        }
        .card-title {
          font-size: 0.94rem;
          font-weight: 700;
          line-height: 1.45;
          margin-bottom: 8px;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
          min-height: 4.1em;
        }
        .card-title a:hover { color: var(--red); }
        .card-rating {
          font-size: 0.8rem;
          color: var(--muted);
          margin-bottom: 10px;
        }
        .card-rating .stars {
          color: #d97706;
          font-weight: 700;
        }
        .price-box {
          background: #fffaf0;
          border: 1px solid #feebc8;
          border-radius: 10px;
          padding: 10px 12px;
          margin-top: auto;
          margin-bottom: 12px;
        }
        .price-old {
          font-size: 0.78rem;
          color: var(--muted);
        }
        .price-current {
          font-size: 1.45rem;
          font-weight: 900;
          color: var(--red);
          line-height: 1.2;
        }
        .price-current .tax-in {
          font-size: 0.72rem;
          font-weight: 500;
          color: var(--muted);
        }
        .price-save {
          font-size: 0.8rem;
          font-weight: 700;
          color: #b91c1c;
          margin-top: 2px;
        }
        .btn-amazon {
          display: block;
          text-align: center;
          background: linear-gradient(180deg, #ffb340 0%, #ff9900 100%);
          color: #111;
          font-weight: 800;
          font-size: 0.95rem;
          padding: 11px 14px;
          border-radius: 9px;
          box-shadow: 0 2px 5px rgba(255,153,0,0.35);
          transition: filter 0.15s, transform 0.1s;
        }
        .btn-amazon:hover {
          filter: brightness(1.04);
          transform: translateY(-1px);
        }
        .sub-actions {
          display: flex;
          gap: 8px;
          margin-top: 8px;
        }
        .btn-detail, .btn-rakuten {
          flex: 1;
          text-align: center;
          font-size: 0.76rem;
          font-weight: 600;
          padding: 6px 8px;
          border-radius: 7px;
          border: 1px solid var(--border);
          background: #f8fafc;
          color: #475569;
        }
        .btn-rakuten:hover, .btn-detail:hover {
          background: #e2e8f0;
        }
        /* 個別商品ページ (Hero) */
        .featured-box {
          background: #fff;
          border: 2px solid var(--amazon);
          border-radius: 16px;
          padding: 24px;
          margin-bottom: 32px;
          display: grid;
          grid-template-columns: 340px 1fr;
          gap: 28px;
          box-shadow: 0 8px 28px rgba(0,0,0,0.08);
        }
        @media (max-width: 768px) {
          .featured-box { grid-template-columns: 1fr; padding: 16px; gap: 16px; }
        }
        .featured-img-wrap {
          display: flex;
          align-items: center;
          justify-content: center;
          background: #fff;
          padding: 16px;
          border-radius: 12px;
          border: 1px solid #f1f5f9;
          min-height: 260px;
        }
        .featured-img-wrap img {
          max-width: 100%;
          max-height: 300px;
          object-fit: contain;
        }
        .featured-info h1 {
          font-size: 1.3rem;
          line-height: 1.45;
          margin: 10px 0 12px;
        }
        .featured-cta {
          display: inline-block;
          width: 100%;
          text-align: center;
          background: linear-gradient(180deg, #ff4d4d 0%, #e11d48 100%);
          color: #fff;
          font-size: 1.15rem;
          font-weight: 900;
          padding: 15px 20px;
          border-radius: 12px;
          box-shadow: 0 4px 14px rgba(225,29,72,0.35);
          margin-top: 12px;
        }
        .featured-cta:hover { filter: brightness(1.06); }
        .section-heading {
          font-size: 1.25rem;
          font-weight: 800;
          margin: 10px 0 16px;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .site-footer {
          text-align: center;
          color: var(--muted);
          font-size: 0.78rem;
          padding: 30px 16px;
          border-top: 1px solid var(--border);
          background: #fff;
        }
        """

    def _render_index_html(self, deals: List[dict], now_str: str) -> str:
        cards_html = "\n".join(self._render_card_html(d, is_root=True) for d in deals)
        # カテゴリは統一リスト(CATEGORIES)の順で、掲載商品が存在するものだけ表示
        present = {d["category"] for d in deals}
        categories = ["すべて"] + [c for c in CATEGORIES if c in present]
        categories += sorted(c for c in present if c not in CATEGORIES)

        cat_buttons = "\n".join(
            f'<button class="cat-btn{" active" if c == "すべて" else ""}" data-cat="{html.escape(c)}">{html.escape(c)}</button>'
            for c in categories
        )

        deals_json = json.dumps(deals, ensure_ascii=False)

        top_og_meta = ""
        if deals and self.base_url:
            top_asin = deals[0]["asin"]
            self._generate_deal_ogp_image(top_asin, deals[0].get("image_url", ""))
            top_ogp = OGP_DIR / f"{top_asin}.jpg"
            if top_ogp.exists():
                top_og_img = f"{self.base_url}/ogp/{top_asin}.jpg"
                top_og_meta = f"""  <meta property="og:image" content="{top_og_img}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:image" content="{top_og_img}">"""

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(self.site_title)}</title>
  <meta name="description" content="Amazonのタイムセール・急激な値下がり大特価商品をリアルタイム自動検知してまとめた特売速報サイトです。">
  <meta property="og:title" content="{html.escape(self.site_title)}">
  <meta property="og:description" content="Amazonのタイムセール・大幅割引商品をリアルタイム自動更新中！">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary_large_image">
{top_og_meta}
  <style>{self._common_css()}</style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a href="index.html" class="brand">
        <span>⚡ {html.escape(self.site_title)}</span>
        <span class="brand-badge">大特価タグ</span>
      </a>
      <div class="header-meta">
        <span>最終更新: {now_str}</span>
        <span class="pr-notice">※当サイトはAmazonアソシエイト・プログラムに参加しています(PR)</span>
      </div>
    </div>
  </header>

  <main class="container">
    <!-- URLパラメータ ?asin= 指定時のピックアップ表示枠 -->
    <div id="spotlight-area"></div>

    <section class="filter-panel">
      <div class="search-row">
        <input type="search" id="searchInput" class="search-input" placeholder="🔍 商品名・ブランド名で検索 (例: Anker, コカ・コーラ, SSD)...">
        <div class="sort-group">
          <button class="sort-btn active" data-sort="new">⚡ 新着順</button>
          <button class="sort-btn" data-sort="discount">🔥 割引率順</button>
          <button class="sort-btn" data-sort="savings">💎 値引き額順</button>
          <button class="sort-btn" data-sort="price">💰 価格が安い順</button>
        </div>
      </div>
      <div class="cat-row" id="catRow">
        {cat_buttons}
      </div>
    </section>

    <h2 class="section-heading">🔥 現在開催中のAmazon大特価・タイムセール一覧 ({len(deals)}件)</h2>
    <div class="deals-grid" id="dealsGrid">
      {cards_html}
    </div>
    <div style="text-align:center;margin:22px 0;">
      <button id="moreBtn" class="more-btn" style="padding:12px 28px;font-size:1rem;display:none;">もっと見る</button>
    </div>
  </main>

  <footer class="site-footer">
    <p>※Amazonのアソシエイトとして、当メディアは適格販売により収入を得ています。</p>
    <p>※掲載されている価格・割引率は自動検知時点の情報です。最新の価格・在庫状況はリンク先のAmazon商品ページにてご確認ください。</p>
  </footer>

  <script>
    const DEALS_DATA = {deals_json};

    // ?asin= パラメータで流入した場合、最上部に該当商品を特大ピックアップ表示
    (function() {{
      const params = new URLSearchParams(window.location.search);
      const targetAsin = params.get("asin");
      if (!targetAsin) return;
      const item = DEALS_DATA.find(d => d.asin === targetAsin);
      if (!item) return;
      const savings = Math.max(0, item.regular_price - item.current_price);
      const box = document.getElementById("spotlight-area");
      box.innerHTML = `
        <div class="featured-box">
          <div class="featured-img-wrap">
            <img src="${{item.image_url}}" alt="">
          </div>
          <div class="featured-info">
            <div>
              <span class="badge-discount" style="font-size:1rem;padding:5px 12px;">🎯 ピックアップ特価：${{item.discount_percent}}% OFF</span>
              <span class="badge-category">${{item.category}}</span>
            </div>
            <h1>${{item.title}}</h1>
            <div class="card-rating">
              <span class="stars">⭐ ${{item.rating.toFixed(1)}}</span>
              <span>(${{item.reviews_count.toLocaleString()}}件のレビュー)</span>
            </div>
            <div class="price-box" style="margin:14px 0;">
              <div class="price-old">参考価格: <s>￥${{item.regular_price.toLocaleString()}}</s></div>
              <div class="price-current" style="font-size:1.85rem;">￥${{item.current_price.toLocaleString()}} <span class="tax-in">(税込)</span></div>
              <div class="price-save">🔥 今なら ￥${{savings.toLocaleString()}} お得！</div>
            </div>
            <a href="${{item.affiliate_url}}" target="_blank" rel="nofollow sponsored noopener" class="featured-cta">
              👉 Amazonでセール価格・在庫を見る
            </a>
          </div>
        </div>
      `;
    }})();

    // フィルタリング＆ソート＆「もっと見る」処理
    const PAGE_SIZE = 50;
    let visibleLimit = PAGE_SIZE;
    const grid = document.getElementById("dealsGrid");
    const cards = Array.from(grid.querySelectorAll(".deal-card"));
    const searchInput = document.getElementById("searchInput");
    const moreBtn = document.getElementById("moreBtn");
    let currentCat = "すべて";

    function applyFilter() {{
      const q = searchInput.value.trim().toLowerCase();
      let shown = 0, matched = 0;
      Array.from(grid.querySelectorAll(".deal-card")).forEach(card => {{
        const matchCat = (currentCat === "すべて" || card.dataset.category === currentCat);
        const matchText = (!q || card.dataset.title.includes(q));
        if (matchCat && matchText) {{
          matched++;
          if (shown < visibleLimit) {{ card.style.display = ""; shown++; }} else {{ card.style.display = "none"; }}
        }} else {{
          card.style.display = "none";
        }}
      }});
      moreBtn.style.display = (matched > shown) ? "" : "none";
      moreBtn.textContent = "もっと見る (残り" + (matched - shown) + "件)";
    }}

    moreBtn.addEventListener("click", () => {{ visibleLimit += PAGE_SIZE; applyFilter(); }});
    searchInput.addEventListener("input", () => {{ visibleLimit = PAGE_SIZE; applyFilter(); }});

    document.querySelectorAll(".cat-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".cat-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        currentCat = btn.dataset.cat;
        visibleLimit = PAGE_SIZE;
        applyFilter();
      }});
    }});

    document.querySelectorAll(".sort-btn").forEach((btn, idx) => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const mode = btn.dataset.sort;
        const sorted = [...cards];
        if (mode === "discount") {{
          sorted.sort((a, b) => Number(b.dataset.discount) - Number(a.dataset.discount));
        }} else if (mode === "savings") {{
          sorted.sort((a, b) => Number(b.dataset.savings) - Number(a.dataset.savings));
        }} else if (mode === "price") {{
          sorted.sort((a, b) => Number(a.dataset.price) - Number(b.dataset.price));
        }}
        sorted.forEach(c => grid.appendChild(c));
        visibleLimit = PAGE_SIZE;
        applyFilter();
      }});
    }});

    applyFilter();
  </script>
</body>
</html>
"""

    def _render_deal_page_html(self, target: dict, other_deals: List[dict], now_str: str) -> str:
        asin = html.escape(target["asin"])
        title = html.escape(target["title"])
        price = target["current_price"]
        reg_price = target["regular_price"]
        disc = target["discount_percent"]
        savings = max(0, reg_price - price)
        img = html.escape(target["image_url"])
        cat = html.escape(target["category"])
        aff_url = html.escape(target["affiliate_url"])
        rating = target["rating"]
        reviews = target["reviews_count"]
        time_str = _format_jst(target["posted_at"])

        og_title = f"🔥【{disc}% OFF】￥{reg_price:,}➡️￥{price:,}｜{title[:60]}"
        og_desc = f"今なら￥{savings:,}お得！Amazonタイムセール特価品＆同時開催中の大特価セール一覧はこちら。"

        other_cards = "\n".join(self._render_card_html(d, is_root=False) for d in other_deals)

        deal_page_url = f"{self.base_url}/deals/{asin}.html" if self.base_url else ""

        # X(Twitter)リンクカードで商品全体が完全に見えるよう1200x630白背景のOGP画像を生成
        ogp_path = self._generate_deal_ogp_image(target["asin"], target.get("image_url", ""))
        if ogp_path and self.base_url:
            og_img = f"{self.base_url}/ogp/{asin}.jpg"
        else:
            og_img = img

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{og_title} - {html.escape(self.site_title)}</title>
  <meta name="description" content="{html.escape(og_desc)}">
  <link rel="canonical" href="{deal_page_url}">
  <meta property="og:title" content="{og_title}">
  <meta property="og:description" content="{html.escape(og_desc)}">
  <meta property="og:url" content="{deal_page_url}">
  <meta property="og:site_name" content="{html.escape(self.site_title)}">
  <meta property="og:image" content="{og_img}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{og_title}">
  <meta name="twitter:description" content="{html.escape(og_desc)}">
  <meta name="twitter:image" content="{og_img}">
  <style>{self._common_css()}</style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a href="../index.html" class="brand">
        <span>⚡ {html.escape(self.site_title)}</span>
        <span class="brand-badge">大特価タグ</span>
      </a>
      <div class="header-meta">
        <a href="../index.html" style="color:#fff;font-weight:700;text-decoration:underline;">🏠 全セール一覧へ戻る</a>
        <span class="pr-notice">※Amazonアソシエイト参加中(PR)</span>
      </div>
    </div>
  </header>

  <main class="container">
    <!-- メイン注目商品 -->
    <section class="featured-box">
      <div class="featured-img-wrap">
        <a href="{aff_url}" target="_blank" rel="nofollow sponsored noopener">
          <img src="{img}" alt="{title}">
        </a>
      </div>
      <div class="featured-info">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <span class="badge-discount" style="font-size:1.05rem;padding:5px 14px;">🔥 {disc}% OFF 大特価</span>
          <span class="badge-category">{cat}</span>
          <span class="badge-time">検知時刻: {time_str}</span>
        </div>
        <h1>{title}</h1>
        <div class="card-rating" style="font-size:0.95rem;">
          <span class="stars">⭐ {rating:.1f}</span>
          <span>({reviews:,}件のカスタマーレビュー)</span>
        </div>
        <div class="price-box" style="margin:16px 0;padding:14px 16px;">
          <div class="price-old" style="font-size:0.9rem;">参考/過去価格: <s>￥{reg_price:,}</s></div>
          <div class="price-current" style="font-size:2rem;">￥{price:,} <span class="tax-in">(税込)</span></div>
          <div class="price-save" style="font-size:0.95rem;">💡 通常より ￥{savings:,} お得に購入可能！</div>
        </div>
        <a href="{aff_url}" target="_blank" rel="nofollow sponsored noopener" class="featured-cta">
          🛒 Amazonで詳細・最新価格を見る
        </a>
        <p style="font-size:0.75rem;color:#64748b;margin-top:8px;">
          ※タイムセールは在庫切れや期間終了により予告なく終了する場合があります。
        </p>
      </div>
    </section>

    <!-- 回遊用：同時開催中の大特価セール一覧 -->
    <h2 class="section-heading">🔥 あわせてチェック！同時開催中の大特価セール商品</h2>
    <div class="deals-grid">
      {other_cards}
    </div>
  </main>

  <footer class="site-footer">
    <p><a href="../index.html" style="font-weight:700;color:#0f172a;">👉 {html.escape(self.site_title)} トップページ（全セール商品一覧）を見る</a></p>
    <p style="margin-top:8px;">※Amazonのアソシエイトとして、当メディアは適格販売により収入を得ています。</p>
  </footer>
</body>
</html>
"""


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Amazon大特価まとめサイト生成ツール")
    parser.add_argument("--open", action="store_true", help="生成後にブラウザでサイトを開きます")
    args = parser.parse_args()

    gen = SiteGenerator()
    index_path = gen.build_site()
    print(f"✅ サイト生成完了: {index_path.resolve()}")
    if args.open:
        webbrowser.open(index_path.resolve().as_uri())


if __name__ == "__main__":
    main()
