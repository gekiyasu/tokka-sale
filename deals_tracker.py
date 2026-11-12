import html as html_module
import re
import random
import math
import logging
import requests
from typing import List, Optional
from models import ProductDeal
from config import config
from db import Database, normalize_category

logger = logging.getLogger(__name__)

class DealsTracker:
    def __init__(self, api_key: str = "", db: Optional[Database] = None):
        self.api_key = api_key or config.keepa_api_key
        self.db = db or Database()

    def sync_live_amazon_data(self, deal: ProductDeal) -> bool:
        """実際のAmazon.co.jp商品ページからリアルタイムの価格・評価・レビュー数を取得して完全一致させる"""
        if hasattr(deal, "_live_synced"):
            return bool(getattr(deal, "_live_synced"))
        url = f"https://www.amazon.co.jp/dp/{deal.asin}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }
        try:
            res = requests.get(url, headers=headers, timeout=12)
            if res.status_code == 404 or "ページが見つかりません" in res.text:
                logger.warning(f"商品ページが存在しません (ASIN: {deal.asin})")
                return False

            html = res.text

            # 0. 商品タイトルと公式商品画像URLの抽出 (id="productTitle" と id="landingImage" タグ本体の属性のみに厳密限定)
            title_match = re.search(r'id="productTitle"[^>]*>([\s\S]*?)</span>', html)
            if not title_match:
                logger.warning(f"商品タイトルが取得できません: {deal.asin}")
                return False
            clean_title = html_module.unescape(re.sub(r'\s+', ' ', title_match.group(1)).strip())
            if not clean_title:
                return False

            # カタログや検索キーワードと実際のページ商品名が一致しているか厳密チェック（無関係な商品の誤投稿を完全防止）
            expected_kw = getattr(deal, "_expected_keyword", "")
            if not expected_kw and deal.title and deal.title != "Amazon注目セール商品":
                expected_kw = deal.title.split()[0][:4]
            if expected_kw and expected_kw.lower() not in clean_title.lower():
                logger.warning(
                    f"⚠️ 商品名不一致のためスキップ ({deal.asin}): 期待キーワード='{expected_kw}' / 実際のページ='{clean_title[:30]}...'"
                )
                return False

            # 互換ケースや保護フィルム等のサードパーティ付属品を除外
            for ng_word in ["互換品", "ケースのみ", "保護フィルム", "カバーのみ", "収納ケース"]:
                if ng_word in clean_title:
                    logger.warning(f"⚠️ 互換品・ケース類のためスキップ ({deal.asin}): '{clean_title[:30]}...'")
                    return False

            deal.title = clean_title

            landing_match = re.search(r'<img[^>]*id="landingImage"[^>]*>', html)
            if landing_match:
                img_tag = landing_match.group(0)
                img_url_match = (
                    re.search(r'data-old-hires="(https://m\.media-amazon\.com/images/I/[^"]+)"', img_tag)
                    or re.search(r'data-a-dynamic-image="\{&quot;(https://m\.media-amazon\.com/images/I/[^&"]+)', img_tag)
                    or re.search(r'src="(https://m\.media-amazon\.com/images/I/[^"]+)"', img_tag)
                )
                if img_url_match:
                    deal.image_url = html_module.unescape(img_url_match.group(1))
                else:
                    return False
            else:
                logger.warning(f"メイン商品画像タグ(landingImage)が見つかりません: {deal.asin}")
                return False

            # メイン価格エリア (corePriceDisplay_desktop_feature_div / apex_desktop) を切り出し
            price_section = html
            core_idx = html.find('id="corePriceDisplay_desktop_feature_div"')
            if core_idx == -1:
                core_idx = html.find('id="apex_desktop"')
            if core_idx != -1:
                price_section = html[core_idx:core_idx + 8000]

            # 1. 現在価格の抽出 (priceToPay を最優先)
            price_match = (
                re.search(r'priceToPay[\s\S]{1,800}?class="a-price-whole">([0-9,]+)', price_section)
                or re.search(r'class="a-price-whole">([0-9,]+)', price_section)
                or re.search(r'"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)', price_section)
            )
            if not price_match:
                logger.warning(f"現在価格が取得できません（在庫切れ等の可能性）: {deal.asin}")
                return False

            raw_price = price_match.group(1).replace(",", "").split(".")[0]
            live_price = int(raw_price)
            if live_price <= 0:
                return False

            # CVR最大化フィルタ: Xタイムラインで即決・衝動買いされやすい実用価格帯 (500円〜35,000円) にフォーカス
            # 5万円以上の超高額品は「見て終わり(冷やかしクリック)」になりやすくCVRを著しく悪化させるため除外
            if live_price < 500 or live_price > 35000:
                logger.warning(f"⚠️ CVR最適化のため即決対象外の価格帯です (￥{live_price:,}) -> スキップ: {deal.asin}")
                return False

            deal.current_price = live_price

            # 2. ページ上に実際に表示されている参考価格・過去価格 (basisPrice) と割引率の抽出
            basis_match = re.search(
                r'basisPrice[\s\S]{1,1000}?class="a-offscreen">[￥¥]([0-9,]+)</span>',
                price_section
            )
            disc_match = re.search(r'savingsPercentage[^>]*>\s*-([0-9]+)%', price_section)

            if basis_match:
                live_regular = int(basis_match.group(1).replace(",", ""))
                deal.regular_price = live_regular
            elif disc_match:
                disc_pct = int(disc_match.group(1))
                deal.discount_percent = disc_pct
                deal.regular_price = int(round(deal.current_price / (1.0 - disc_pct / 100.0)))
            else:
                # ページ上に割引表示（過去価格・参考価格）が無い商品は「現在セール中ではない」と判定してスキップ
                logger.warning(f"⚠️ ページ上に割引（過去価格/参考価格）の表示がないためスキップします: {deal.asin} (現在価格: ￥{deal.current_price:,})")
                return False

            # 転売価格・高騰チェック（現在価格が定価/参考価格以上の場合はセールではないためスキップ）
            if deal.current_price >= deal.regular_price:
                logger.warning(
                    f"⚠️ 現在セール価格ではありません（現在: ￥{deal.current_price:,} / 参考: ￥{deal.regular_price:,}）-> スキップ: {deal.asin}"
                )
                return False

            # 割引率の確定
            if disc_match:
                deal.discount_percent = int(disc_match.group(1))
            else:
                deal.discount_percent = int(round(((deal.regular_price - deal.current_price) / deal.regular_price) * 100))

            # 3. 星評価の抽出 (id="acrPopover" または averageCustomerReviews 内のメイン評価のみを対象)
            rating_match = (
                re.search(r'id="acrPopover"[^>]*title="5つ星のうち\s*([0-9.]+)"', html)
                or re.search(r'id="averageCustomerReviews"[\s\S]{1,1500}?5つ星のうち\s*([0-9.]+)', html)
            )
            if rating_match:
                deal.rating = float(rating_match.group(1))

            # 4. レビュー件数の抽出 (id="acrCustomerReviewText" 内の数値を対象)
            reviews_match = re.search(r'id="acrCustomerReviewText"[^>]*>\s*\(?([0-9,]+)', html)
            if reviews_match:
                deal.reviews_count = int(reviews_match.group(1).replace(",", ""))

            logger.info(
                f"✅ リアルタイム完全一致同期 ({deal.asin}): "
                f"商品='{deal.title[:32]}...', "
                f"現在価格=￥{deal.current_price:,}, 参考=￥{deal.regular_price:,} ({deal.discount_percent}% OFF), "
                f"画像={deal.image_url}"
            )
            setattr(deal, "_live_synced", True)
            return True
        except Exception as e:
            logger.warning(f"リアルタイム情報の取得中にエラーが発生しました ({deal.asin}: {e})")
            setattr(deal, "_live_synced", False)
            return False

    def _discover_live_amazon_deals(self) -> List[ProductDeal]:
        """Amazon.co.jpの検索結果から現在セール中の人気商品をリアルタイム自動収集"""
        search_queries = [
            # CVR激高ジャンル: 日常消耗品・飲料・食品 (1,000〜3,000円台の即決・まとめ買い)
            ("コカ・コーラ 24本 セール", "コカ・コーラ", "食品・飲料"),
            ("ラベルレス 炭酸水 24本 セール", "炭酸水", "食品・飲料"),
            ("天然水 500ml 24本 セール", "水", "食品・飲料"),
            ("綾鷹 525ml 24本 セール", "お茶", "食品・飲料"),
            ("ザバス プロテイン セール", "ザバス", "食品・飲料"),
            ("アタックZERO 詰め替え セール", "アタック", "日用品"),
            ("めぐりズム ホットアイマスク セール", "めぐりズム", "日用品"),
            ("バブ 炭酸入浴剤 セール", "バブ", "日用品"),
            # 定番人気ガジェット: 手頃な価格帯 (1,000〜5,000円台の即決品)
            ("Anker 充電器 セール", "Anker", "ガジェット"),
            ("Anker USB-C ケーブル セール", "Anker", "ガジェット"),
            ("CIO 充電器 セール", "CIO", "ガジェット"),
            ("CIO 巻き取り ケーブル セール", "CIO", "ガジェット"),
            ("UGREEN 充電器 セール", "UGREEN", "ガジェット"),
            ("Fire TV Stick セール", "Fire TV", "ガジェット"),
            ("ロジクール マウス セール", "ロジクール", "PC周辺機器"),
            ("エレコム 電源タップ セール", "エレコム", "PC・スマホ周辺機器"),
            ("サンディスク microSD セール", "SanDisk", "PC周辺機器"),
            ("バッファロー 外付けSSD セール", "バッファロー", "PC周辺機器"),
            ("ティファール フライパン セール", "ティファール", "キッチン"),
            ("アイリスオーヤマ セール", "アイリス", "日用品・家電"),
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9",
        }
        discovered: List[ProductDeal] = []

        # 自動PDCA学習ループ: 過去7日間のカテゴリ別クリック実績に基づく重み付け選定
        try:
            click_stats = self.db.get_category_click_stats(days=7)
        except Exception as e:
            logger.debug(f"[DealsTracker] クリック統計取得スキップ: {e}")
            click_stats = {}

        total_clicks = sum(click_stats.values())
        if total_clicks > 0:
            top_cat = max(click_stats.items(), key=lambda x: x[1])
            logger.info(f"📈 [Auto-PDCA] 過去7日間のクリック学習中 (計{total_clicks}回 / 首位: {top_cat[0]} {top_cat[1]}回)")

        # 各検索クエリの重みを算出 (Efraimidis-Spirakis アルゴリズム)
        # 基本重み 1.0 + log2(1 + クリック数) * 1.5 で人気ジャンルの優先度を自動傾斜配分
        scored_queries = []
        for q_tuple in search_queries:
            query, expected_kw, category = q_tuple
            cat_clean = normalize_category(category)
            clicks = click_stats.get(cat_clean, 0)
            weight = 1.0 + math.log2(1.0 + max(0, clicks)) * 1.5
            # 重み付き乱数スコア: score = random() ** (1 / weight)
            rand_score = random.random() ** (1.0 / max(0.1, weight))
            scored_queries.append((rand_score, q_tuple))

        # スコア降順に並び替え (重みに比例した確率で重複なし抽出)
        scored_queries.sort(key=lambda x: x[0], reverse=True)
        shuffled_queries = [q for _, q in scored_queries]

        for query, expected_kw, category in shuffled_queries:
            if len(discovered) >= 12:
                break
            try:
                url = f"https://www.amazon.co.jp/s?k={requests.utils.quote(query)}"
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code != 200:
                    continue
                # 検索結果から実在するASINを抽出
                asins = list(dict.fromkeys(re.findall(r'data-asin="(B0[A-Z0-9]{8})"', res.text)))
                for asin in asins[:6]:
                    deal = ProductDeal(
                        asin=asin,
                        title="Amazon注目セール商品",
                        current_price=1000,
                        regular_price=1500,
                        discount_percent=20,
                        image_url="",
                        rating=4.3,
                        reviews_count=100,
                        category=category,
                        highlight="",
                    )
                    deal._expected_keyword = expected_kw
                    deal.generate_affiliate_url(config.amazon_tag)
                    discovered.append(deal)
            except Exception as e:
                logger.debug(f"リアルタイム検索収集スキップ ({query}: {e})")

        return discovered

    def fetch_deals(self) -> List[ProductDeal]:
        """セール品一覧を取得（APIキーがない場合はリアルタイム検索＋厳選カタログを返す）"""
        if not self.api_key:
            logger.info("Amazon.co.jpから現在セール中の人気商品をリアルタイム検索しています...")
            live_deals = self._discover_live_amazon_deals()
            catalog_deals = self._get_mock_deals()
            random.shuffle(catalog_deals)
            return live_deals + catalog_deals

        return self._fetch_keepa_deals()

    def _fetch_keepa_deals(self) -> List[ProductDeal]:
        """Keepa Deal API (Domain 5 = Amazon Japan) からセール情報を取得"""
        url = "https://api.keepa.com/deal"
        payload = {
            "key": self.api_key,
            "domain": 5, # 5: amazon.co.jp
            "selection": {
                "page": 0,
                "perPage": 20,
                "deltaPercentRange": [config.min_discount_percent, 100], # 値下げ率フィルタ
                "hasReviews": True,
                "sortType": 4, # 割引額・率ソート
                "dateRange": 1 # 過去1日以内の変動
            }
        }
        
        try:
            response = requests.post(url, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            deals_list: List[ProductDeal] = []
            deals_data = data.get("deals", {}).get("dr", [])
            
            for d in deals_data:
                asin = d.get("asin")
                title = d.get("title", "注目セール商品")
                current_price = int(d.get("current", [0])[0])
                regular_price = int(d.get("avg", [0])[0] or current_price)
                
                if current_price <= 0 or regular_price <= 0:
                    continue
                
                discount_percent = int(((regular_price - current_price) / regular_price) * 100)
                if discount_percent < config.min_discount_percent:
                    continue
                
                rating = float(d.get("rating", 40)) / 10.0
                reviews_count = int(d.get("reviewCount", 50))
                
                if rating < config.min_rating or reviews_count < config.min_reviews_count:
                    continue
                
                image_id = d.get("image", [""])[0]
                image_url = f"https://images-na.ssl-images-amazon.com/images/I/{image_id}" if image_id else ""
                
                deal = ProductDeal(
                    asin=asin,
                    title=title,
                    current_price=current_price,
                    regular_price=regular_price,
                    discount_percent=discount_percent,
                    image_url=image_url,
                    rating=rating,
                    reviews_count=reviews_count,
                    category=d.get("category", "General")
                )
                deal.generate_affiliate_url(config.amazon_tag)
                deals_list.append(deal)
                
            return deals_list
        except Exception as e:
            logger.error(f"Keepa Deals APIの取得に失敗しました: {e}")
            return []

    def _get_mock_deals(self) -> List[ProductDeal]:
        """実在＆セール確認済みのAmazon.co.jp人気商品のフォールバックカタログ"""
        verified_asins = [
            ("B0CQ29L3RM", "エレコム", "PC・スマホ周辺機器"),
            ("B004Y9IXZW", "コカ・コーラ", "飲料・食品"),
            ("B0FRFSFCQH", "Anker", "ガジェット"),
            ("B0BQYPD2KH", "アイリス", "家電"),
            ("B0GWHZ4SHZ", "", "注目セール"),
            ("B0HCTJMGH8", "", "注目セール"),
            ("B0FMHZ3KVP", "", "注目セール"),
            ("B0GFM3CXM4", "", "注目セール"),
        ]
        catalog = []
        for asin, expected_kw, category in verified_asins:
            deal = ProductDeal(
                asin=asin,
                title="Amazon注目セール商品",
                current_price=1000,
                regular_price=1500,
                discount_percent=20,
                image_url="",
                rating=4.3,
                reviews_count=100,
                category=category,
                highlight="",
            )
            deal._expected_keyword = expected_kw
            deal.generate_affiliate_url(config.amazon_tag)
            catalog.append(deal)
        return catalog
