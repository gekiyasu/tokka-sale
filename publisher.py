import logging
import time
from pathlib import Path
import requests
from typing import List, Optional
from models import ProductDeal
from config import config

logger = logging.getLogger(__name__)

class BasePublisher:
    def publish(self, deal: ProductDeal) -> bool:
        raise NotImplementedError

class XPublisher(BasePublisher):
    """X (旧Twitter) 投稿ドライバー (Selenium ブラウザ自動操作 / API v2 ハイブリッド対応)"""
    def __init__(self):
        self.enabled = config.enable_x
        self.use_selenium = config.x_use_selenium
        self.profile_dir = Path(__file__).parent / config.x_chrome_profile_dir
        self.client = None

        if self.enabled:
            if self.use_selenium:
                logger.info(f"X (Twitter) Selenium Publisher を有効化しました (プロファイル: {self.profile_dir.name})")
            else:
                try:
                    import tweepy
                    self.client = tweepy.Client(
                        bearer_token=config.x_bearer_token,
                        consumer_key=config.x_api_key,
                        consumer_secret=config.x_api_secret,
                        access_token=config.x_access_token,
                        access_token_secret=config.x_access_secret
                    )
                    logger.info("X (Twitter) API Publisher を初期化しました。")
                except Exception as e:
                    logger.error(f"X Clientの初期化に失敗しました: {e}")
                    self.enabled = False

    def _prepare_x_image(self, image_url: str) -> Optional[Path]:
        """商品画像をダウンロードし、Xのタイムライン・リンクカード(1200x630 / 1.91:1)で見切れずに商品全体が収まるよう白背景中央に配置して一時保存"""
        if not image_url:
            return None
        try:
            res = requests.get(image_url, timeout=10)
            res.raise_for_status()
            img_bytes = res.content
            if len(img_bytes) < 1000:
                return None

            import io
            from PIL import Image

            W, H = 1200, 630
            canvas = Image.new("RGB", (W, H), (255, 255, 255))
            prod_img = Image.open(io.BytesIO(img_bytes))
            if prod_img.mode in ("RGBA", "P", "LA"):
                bg = Image.new("RGB", prod_img.size, (255, 255, 255))
                if prod_img.mode != "RGBA":
                    prod_img = prod_img.convert("RGBA")
                bg.paste(prod_img, mask=prod_img.split()[3])
                prod_img = bg
            else:
                prod_img = prod_img.convert("RGB")

            # Xのタイムライン表示・カード角丸(border-radius)でも上下左右が一切見切れない安全マージン
            # 最大サイズ 900x480 (上下マージン各75px以上、左右マージン各150px以上)
            prod_img.thumbnail((900, 480), Image.Resampling.LANCZOS)
            px = (W - prod_img.width) // 2
            py = (H - prod_img.height) // 2
            canvas.paste(prod_img, (px, py))

            temp_path = Path(__file__).parent / "temp_x_post.jpg"
            canvas.save(temp_path, format="JPEG", quality=92, optimize=True)
            return temp_path.resolve()
        except Exception as e:
            logger.warning(f"[X] 商品画像の準備をスキップしました: {e}")
            return None

    def _create_driver(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = Options()
        options.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,900")
        if config.x_headless:
            options.add_argument("--headless=new")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
        )
        return driver

    def _wait_for_page_deployment(self, url: str, timeout: int = 150) -> bool:
        """GitHub Pages等のクッションページが実際にインターネット上で 200 OK になるまで待機"""
        if not url or not url.startswith("http"):
            return True
        logger.info(f"⏳ クッションページの公開反映(200 OK)を待機しています: {url}")
        start = time.time()
        while time.time() - start < timeout:
            try:
                res = requests.get(url, timeout=6)
                if res.status_code == 200 and len(res.text) > 1000:
                    logger.info(f"✅ クッションページの公開を確認しました (経過: {int(time.time() - start)}秒)")
                    time.sleep(3.0)
                    return True
            except Exception:
                pass
            time.sleep(5)
        logger.warning(f"⚠️ クッションページの反映確認がタイムアウトしました ({timeout}秒)")
        return False

    def _publish_via_selenium(self, deal: ProductDeal) -> bool:
        if not self.profile_dir.exists():
            logger.warning(
                "⚠️ [X-Selenium] 初回ログイン用のプロファイルがまだ作成されていません。"
                "Xへ自動投稿するには一度 `python setup_x_login.py` を実行してログインしてください。"
            )
            return False

        from deals_tracker import DealsTracker
        if not DealsTracker().sync_live_amazon_data(deal):
            return False

        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        share_url = deal.get_share_url(config.site_base_url)
        is_thread_mode = (config.x_post_mode == "thread")

        # ツリー投稿時は親ポストにURLを入れず自己リプで案内 / リンク直貼りモード時は本文にURL
        if is_thread_mode:
            text = deal.format_x_thread_parent_text()
            reply_text = deal.format_x_thread_reply_text(share_url=share_url)
        else:
            text = deal.format_x_post_text(share_url=share_url)
            reply_text = ""

        # OGPリンクカードを確実に表示させるため、Webページが公開(200 OK)されるまで待機 (非画像添付時のみ)
        if not config.x_attach_image and not is_thread_mode and share_url.startswith("http"):
            self._wait_for_page_deployment(share_url, timeout=120)

        # 商品画像 (ツリーモード時はタイムライン視認性を最大化するため必須添付)
        need_image = config.x_attach_image or is_thread_mode
        temp_img = self._prepare_x_image(deal.image_url) if need_image else None
        driver = None

        try:
            driver = self._create_driver()
            logger.info(f"[X-Selenium] 投稿画面を開いています (モード: {config.x_post_mode}): {deal.asin}")
            driver.get("https://x.com/compose/post")
            time.sleep(3.5)

            current_url = driver.current_url.lower()
            if "login" in current_url or "i/flow" in current_url:
                logger.error(
                    "⚠️ [X-Selenium] Xにログインされていません。先に `python setup_x_login.py` を実行してブラウザで一度ログインしてください。"
                )
                return False

            # アカウントのロック・本人確認要求・凍結を検知したら、自動投稿を長時間停止する
            try:
                page_text = driver.page_source
            except Exception:
                page_text = ""
            if "account/access" in current_url or any(
                kw in page_text for kw in ["アカウントはロックされています", "アカウントが凍結", "Your account is suspended", "Your account has been locked"]
            ):
                from x_guard import XGuard, LOCK_PAUSE_HOURS
                XGuard().pause(LOCK_PAUSE_HOURS, "Xがロック/凍結/本人確認を要求 (ブラウザで状況を確認してください)")
                self._guard_handled = True
                return False

            wait = WebDriverWait(driver, 20)
            textarea = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'))
            )
            textarea.click()
            time.sleep(0.8)

            def _input_text_to_element(el, input_text):
                driver.execute_script(
                    """
                    const el = arguments[0];
                    const text = arguments[1];
                    el.focus();
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const pasteEvent = new ClipboardEvent('paste', {
                        clipboardData: dt,
                        bubbles: true,
                        cancelable: true
                    });
                    el.dispatchEvent(pasteEvent);
                    """,
                    el,
                    input_text,
                )
                time.sleep(1.0)
                entered = driver.execute_script("return (arguments[0].innerText || arguments[0].textContent || '').trim();", el)
                if not entered:
                    bmp_text = "".join(c for c in input_text if ord(c) <= 0xFFFF)
                    el.send_keys(bmp_text)
                    time.sleep(1.0)
                el.send_keys(Keys.ESCAPE)
                time.sleep(0.5)

            # 親ポストのテキストを入力
            _input_text_to_element(textarea, text)

            # 商品画像の添付
            if temp_img and temp_img.exists():
                try:
                    file_input = driver.find_element(By.CSS_SELECTOR, 'input[data-testid="fileInput"]')
                    file_input.send_keys(str(temp_img))
                    wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="attachments"]'))
                    )
                    time.sleep(2.5)
                except Exception as img_err:
                    logger.warning(f"[X-Selenium] 画像添付をスキップしました: {img_err}")

            # ツリー投稿 (自己リプライを追加)
            thread_created = False
            if is_thread_mode and reply_text:
                try:
                    add_btns = driver.find_elements(By.CSS_SELECTOR, '[data-testid="addButton"]')
                    if add_btns:
                        add_btn = add_btns[0]
                        driver.execute_script("arguments[0].click();", add_btn)
                        time.sleep(1.5)
                        reply_areas = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweetTextarea_1"]')
                        if reply_areas:
                            _input_text_to_element(reply_areas[0], reply_text)
                            thread_created = True
                            logger.info("[X-Selenium] ツリー(自己リプライ枠)に入力を完了しました")
                except Exception as th_err:
                    logger.warning(f"[X-Selenium] ツリー作成ボタンの処理に失敗: {th_err}")

                # もしツリー入力枠が作成できなかった場合は親ポストの末尾にフォールバック追加
                if not thread_created:
                    logger.info("[X-Selenium] 単体ポストにフォールバックしてURLを追加します")
                    _input_text_to_element(textarea, f"\n\n👇 詳細・在庫はこちら\n{share_url}")

            # リンクカード(画像プレビュー)が生成されるのを待つ (非画像・非ツリーモード時)
            if not is_thread_mode and not (temp_img and temp_img.exists()):
                try:
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="card.wrapper"]'))
                    )
                    time.sleep(4.0)
                    logger.info("[X-Selenium] リンクカードの生成を確認しました")
                except Exception:
                    logger.warning("[X-Selenium] リンクカードを確認できませんでした(リンクのみで投稿します)")

            # ポスト送信ボタンを押下
            time.sleep(1.5)
            posted = False
            for btn_selector in ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']:
                btns = driver.find_elements(By.CSS_SELECTOR, btn_selector)
                if btns:
                    btn = btns[0]
                    driver.execute_script("arguments[0].click();", btn)
                    posted = True
                    break

            if not posted:
                textarea.send_keys(Keys.CONTROL, Keys.ENTER)

            time.sleep(5.0)
            logger.info(f"[X-Selenium] ツイート送信成功 (ツリーモード: {thread_created}): {deal.asin}")
            return True

        except Exception as e:
            logger.error(f"[X-Selenium] 投稿エラー: {e}")
            return False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if temp_img and temp_img.exists():
                try:
                    temp_img.unlink()
                except Exception:
                    pass

    def publish(self, deal: ProductDeal) -> bool:
        if not self.enabled:
            return False

        # 凍結・制限対策: 投稿時間帯 / 1日の上限 / 投稿間隔 / 自動停止の判定
        from x_guard import XGuard
        guard = XGuard()
        allowed, reason = guard.check()
        if not allowed:
            logger.info(f"[X] 今回はX投稿を見送ります: {reason}")
            return False

        if self.use_selenium:
            ok = self._publish_via_selenium(deal)
        elif not self.client:
            ok = False
        else:
            try:
                text = deal.format_x_post_text()
                response = self.client.create_tweet(text=text)
                logger.info(f"[X-API] ツイート成功 (ID: {response.data['id']})")
                ok = True
            except Exception as e:
                logger.error(f"[X-API] 投稿エラー: {e}")
                ok = False

        if ok:
            guard.record_success()
        elif not getattr(self, "_guard_handled", False):
            guard.record_failure()
        self._guard_handled = False
        return ok

class DiscordPublisher(BasePublisher):
    """Discord Webhook 投稿ドライバー (リッチなEmbed付き)"""
    def __init__(self):
        self.enabled = config.enable_discord and bool(config.discord_webhook_url)

    def publish(self, deal: ProductDeal) -> bool:
        if not self.enabled:
            return False
        
        embed = {
            "title": f"🔥【{deal.discount_percent}% OFF】{deal.title}",
            "url": deal.affiliate_url,
            "color": 0xFF9900,  # Amazon Orange
            "fields": [
                {"name": "セール価格", "value": f"**￥{deal.current_price:,}**", "inline": True},
                {"name": "定価/通常価格", "value": f"~~￥{deal.regular_price:,}~~", "inline": True},
                {"name": "評価", "value": f"⭐ {deal.rating} ({deal.reviews_count:,}件)", "inline": True},
            ],
            "footer": {"text": f"カテゴリ: {deal.category} | Amazonセール速報"}
        }
        if deal.image_url:
            embed["thumbnail"] = {"url": deal.image_url}

        payload = {
            "content": "⚡ **Amazonタイムセール特価品を検知しました！**",
            "embeds": [embed]
        }
        
        try:
            res = requests.post(config.discord_webhook_url, json=payload, timeout=10)
            res.raise_for_status()
            logger.info(f"[Discord] 送信成功: {deal.asin}")
            return True
        except Exception as e:
            logger.error(f"[Discord] 送信エラー: {e}")
            return False

class TelegramPublisher(BasePublisher):
    """Telegram Bot 投稿ドライバー"""
    def __init__(self):
        self.enabled = config.enable_telegram and bool(config.telegram_bot_token) and bool(config.telegram_chat_id)

    def publish(self, deal: ProductDeal) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
        text = deal.format_post_text()
        payload = {
            "chat_id": config.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": False
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            res.raise_for_status()
            logger.info(f"[Telegram] 送信成功: {deal.asin}")
            return True
        except Exception as e:
            logger.error(f"[Telegram] 送信エラー: {e}")
            return False

import re
from datetime import datetime, timezone

class BlueskyPublisher(BasePublisher):
    """Bluesky (AT Protocol) REST API 投稿ドライバー (追加パッケージ不要)"""
    def __init__(self):
        self.enabled = config.enable_bluesky and bool(config.bluesky_handle) and bool(config.bluesky_app_password)
        self.access_jwt = None
        self.did = None
        if self.enabled:
            self._login()

    def _login(self):
        try:
            url = "https://bsky.social/xrpc/com.atproto.server.createSession"
            payload = {
                "identifier": config.bluesky_handle,
                "password": config.bluesky_app_password
            }
            res = requests.post(url, json=payload, timeout=10)
            res.raise_for_status()
            data = res.json()
            self.access_jwt = data.get("accessJwt")
            self.did = data.get("did")
            logger.info("Bluesky への認証に成功しました。")
        except Exception as e:
            logger.error(f"Blueskyのログインに失敗しました: {e}")
            self.enabled = False

    def _parse_facets(self, text: str) -> list:
        """テキスト内のURLやハッシュタグを抽出してBlueskyのクリック可能なfacets形式に変換"""
        facets = []
        utf8_bytes = text.encode("utf-8")
        
        # URLリンク
        url_regex = re.compile(rb"https?://[^\s]+")
        for match in url_regex.finditer(utf8_bytes):
            url_str = match.group(0).decode("utf-8")
            facets.append({
                "index": {
                    "byteStart": match.start(),
                    "byteEnd": match.end()
                },
                "features": [
                    {
                        "$type": "app.bsky.richtext.facet#link",
                        "uri": url_str
                    }
                ]
            })

        # ハッシュタグ (#Amazonセール など)
        tag_regex = re.compile(r"(?<!\w)#([^\s#]+)")
        for match in tag_regex.finditer(text):
            tag_name = match.group(1)
            byte_start = len(text[:match.start()].encode("utf-8"))
            byte_end = len(text[:match.end()].encode("utf-8"))
            facets.append({
                "index": {
                    "byteStart": byte_start,
                    "byteEnd": byte_end
                },
                "features": [
                    {
                        "$type": "app.bsky.richtext.facet#tag",
                        "tag": tag_name
                    }
                ]
            })
        return facets

    def _verify_amazon_url(self, asin: str) -> bool:
        """Amazon.co.jpの商品ページが実在するか（犬の404ページでないか）を確認"""
        try:
            url = f"https://www.amazon.co.jp/dp/{asin}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 404 or "ページが見つかりません" in res.text:
                logger.warning(f"無効なAmazon商品ページを検知しました (ASIN: {asin})")
                return False
            return True
        except Exception as e:
            logger.warning(f"Amazon URL確認中にエラーが発生しました ({e})")
            return True

    def _fit_product_image_to_card(self, img_bytes: bytes) -> bytes:
        """Blueskyの横長リンクカード(1200x630 / 1.91:1)で上下が切れないよう、白背景の中央に商品全体が収まるようリサイズ"""
        import io
        from PIL import Image

        W, H = 1200, 630
        canvas = Image.new("RGB", (W, H), (255, 255, 255))

        prod_img = Image.open(io.BytesIO(img_bytes))
        if prod_img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", prod_img.size, (255, 255, 255))
            if prod_img.mode == "P":
                prod_img = prod_img.convert("RGBA")
            bg.paste(prod_img, mask=prod_img.split()[3])
            prod_img = bg
        else:
            prod_img = prod_img.convert("RGB")

        # 上下左右に十分な余白を持たせて商品全体が100%見えるサイズに縮小 (900x480)
        max_w, max_h = 900, 480
        prod_img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        px = (W - prod_img.width) // 2
        py = (H - prod_img.height) // 2
        canvas.paste(prod_img, (px, py))

        out = io.BytesIO()
        canvas.save(out, format="JPEG", quality=92, optimize=True)
        return out.getvalue()

    def _upload_image(self, image_url: str, deal: ProductDeal = None):
        """画像URLから商品画像をダウンロードし、全体が見える比率(1200x630)に整えてBlueskyへアップロード"""
        if not image_url or not self.access_jwt:
            return None
        try:
            img_data = None
            # すでにSiteGeneratorによって生成済みのローカルOGP画像があればそれを優先利用
            if deal and deal.asin:
                local_ogp = Path(__file__).parent / "docs" / "ogp" / f"{deal.asin}.jpg"
                if local_ogp.exists() and local_ogp.stat().st_size > 1000:
                    try:
                        img_data = local_ogp.read_bytes()
                    except Exception:
                        img_data = None

            if not img_data:
                # 画像取得
                img_res = requests.get(image_url, timeout=10)
                img_res.raise_for_status()
                img_data = img_res.content

                # Amazonが存在しないASINに対して返す1x1透明GIF(43バイト)を弾く
                if len(img_data) < 1000:
                    logger.warning(f"有効な商品画像が存在しません (サイズ: {len(img_data)} bytes)")
                    return None

                try:
                    img_data = self._fit_product_image_to_card(img_data)
                except Exception as ex:
                    logger.warning(f"画像比率の調整をスキップしました ({ex})")

            content_type = "image/jpeg"
            # Blobアップロード
            upload_url = "https://bsky.social/xrpc/com.atproto.repo.uploadBlob"
            headers = {
                "Authorization": f"Bearer {self.access_jwt}",
                "Content-Type": content_type
            }
            res = requests.post(upload_url, headers=headers, data=img_data, timeout=15)
            res.raise_for_status()
            return res.json().get("blob")
        except Exception as e:
            logger.warning(f"画像のアップロードをスキップしました ({e})")
            return None

    def publish(self, deal: ProductDeal) -> bool:
        if not self.enabled or not self.access_jwt:
            return False
        try:
            # 1. Amazon商品ページが実在するか事前検証 ＆ 実際の最新価格をリアルタイム同期
            from deals_tracker import DealsTracker
            if not DealsTracker().sync_live_amazon_data(deal):
                return False

            # 2. 『商品＋期間限定セール』合成画像の生成・アップロード（画像がない商品は投稿しない）
            blob = self._upload_image(deal.image_url, deal=deal)
            if not blob:
                logger.warning(f"[Bluesky] 画像が取得できないため投稿をスキップします: {deal.asin}")
                return False

            text = deal.format_post_text(max_length=280)
            facets = self._parse_facets(text)
            
            url = "https://bsky.social/xrpc/com.atproto.repo.createRecord"
            headers = {"Authorization": f"Bearer {self.access_jwt}"}
            
            card_title = deal.title
            for clutter in ["【2023年秋発売】", "【Amazon.co.jp限定】", "【新型】"]:
                card_title = card_title.replace(clutter, "").strip()

            share_url = deal.get_share_url(config.site_base_url)
            record = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "embed": {
                    "$type": "app.bsky.embed.external",
                    "external": {
                        "uri": share_url,
                        "title": card_title,
                        "description": "",
                        "thumb": blob
                    }
                }
            }
            if facets:
                record["facets"] = facets

            payload = {
                "repo": self.did,
                "collection": "app.bsky.feed.post",
                "record": record
            }

            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 401:  # トークン期限切れ時は再ログインを試行
                self._login()
                if self.access_jwt:
                    headers["Authorization"] = f"Bearer {self.access_jwt}"
                    res = requests.post(url, headers=headers, json=payload, timeout=10)
            
            res.raise_for_status()
            logger.info(f"[Bluesky] 送信成功: {deal.asin}")
            return True
        except Exception as e:
            logger.error(f"[Bluesky] 送信エラー: {e}")
            return False

class MultiPublisher:
    """各SNSへの同時一括配信マネージャー"""
    def __init__(self):
        self.publishers: List[BasePublisher] = [
            BlueskyPublisher(),
            XPublisher(),
            DiscordPublisher(),
            TelegramPublisher(),
        ]

    def broadcast(self, deal: ProductDeal):
        # 配信前に一度だけ実際のAmazon商品ページとリアルタイム同期・検証を行う
        from deals_tracker import DealsTracker
        if not DealsTracker().sync_live_amazon_data(deal):
            return 0

        # 大特価まとめサイト (docs/index.html & docs/deals/<ASIN>.html) を自動更新
        # SNS投稿の成否に関わらず、スキャンで確認できた商品は必ずサイトへ反映する
        site_ready = True
        if config.enable_site_generation:
            try:
                from site_generator import SiteGenerator
                site_gen = SiteGenerator()
                site_gen.build_site(latest_deal=deal)
                # 商品ページが公開サイト上で見えるようになってからSNS投稿する (リンク切れ防止)
                if config.auto_git_push:
                    site_ready = site_gen.wait_until_live(deal.asin)
            except Exception as e:
                logger.warning(f"まとめサイト生成中にエラーが発生しました: {e}")
                site_ready = False
        if not site_ready:
            logger.warning(f"サイト側のページが未公開のためSNS投稿を見送ります: {deal.asin}")
            return 0

        success_count = 0
        any_enabled = False
        for pub in self.publishers:
            if getattr(pub, 'enabled', False):
                any_enabled = True
                pub_name = pub.__class__.__name__
                try:
                    if pub.publish(deal):
                        logger.info(f"✅ [{pub_name}] 投稿成功: {deal.asin}")
                        success_count += 1
                    else:
                        logger.warning(f"⚠️ [{pub_name}] 投稿スキップまたは失敗: {deal.asin}")
                except Exception as e:
                    logger.error(f"❌ [{pub_name}] 投稿例外エラー: {e}")
        
        if not any_enabled:
            # どのSNSも有効化されていない場合はコンソールにシミュレーション出力
            print("\n" + "="*50)
            print("[DRY-RUN / デモ出力] SNSへの投稿プレビュー:")
            print(deal.format_post_text())
            print("="*50 + "\n")
        return success_count
