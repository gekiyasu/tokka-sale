"""
X (旧Twitter) Selenium 初回ログイン＆テスト投稿スクリプト

使い方:
1. 初回ログイン (専用Chromeプロファイルを開いてXに手動ログインし、セッションを保存):
   python setup_x_login.py

2. テスト投稿 (保存されたセッションを使って実際に1件Xへセール商品を投稿):
   python setup_x_login.py --test
"""
import argparse
import logging
import time
from config import config
from publisher import XPublisher
from deals_tracker import DealsTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("XSetup")


def login_session():
    import os
    import subprocess
    from pathlib import Path

    publisher = XPublisher()
    profile_path = publisher.profile_dir.resolve()
    profile_path.mkdir(parents=True, exist_ok=True)

    # 通常の Chrome 実行ファイルを探す（Selenium経由ではなく通常のChromeで開くことでXのログインブロックを完全回避）
    chrome_candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    chrome_exe = next((p for p in chrome_candidates if p.exists()), None)

    print("=" * 65)
    print("🔐 X (Twitter) 自動投稿用 Chrome プロファイルのセットアップ")
    print(f"保存先プロファイル: {profile_path}")
    print("=" * 65)
    print("【やり方（3ステップだけ！）】")
    print("1. 開いた Chrome ウィンドウで X のID・パスワードを入力してログインします。")
    print("2. いつもの X のタイムライン（ホーム画面）が表示されたことを確認します。")
    print("3. 右上の「×」ボタンで Chrome ウィンドウを閉じれば完了です！")
    print("=" * 65)

    if chrome_exe:
        proc = subprocess.Popen([
            str(chrome_exe),
            f"--user-data-dir={profile_path}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "https://x.com/home",
        ])
        proc.wait()
    else:
        driver = publisher._create_driver()
        try:
            driver.get("https://x.com/home")
            for _ in range(900):
                time.sleep(2)
                try:
                    _ = driver.current_url
                except Exception:
                    break
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    print("✅ セットアップ完了！以降の定期実行ではこのログイン状態が自動で維持されます。")


def test_single_post():
    print("=" * 65)
    print("🚀 X (Selenium) へのテスト投稿を開始します...")
    print("=" * 65)

    publisher = XPublisher()
    publisher.enabled = True
    publisher.use_selenium = True

    tracker = DealsTracker()
    deals = tracker.fetch_deals()

    for deal in deals:
        deal.generate_affiliate_url(config.amazon_tag)
        if not tracker.sync_live_amazon_data(deal):
            continue

        print(f"\n📦 テスト対象商品: {deal.title[:45]}...")
        print(f"💰 価格: ￥{deal.regular_price:,} ➜ ￥{deal.current_price:,} ({deal.discount_percent}% OFF)")
        print("📝 投稿テキストプレビュー:")
        print("-" * 40)
        print(deal.format_x_post_text())
        print("-" * 40)

        if publisher.publish(deal):
            print("\n✅ X (Selenium) への画像付きテスト投稿に成功しました！")
            return
        else:
            print("\n❌ 投稿に失敗しました。ログインしていない場合は先に `python setup_x_login.py` を実行してください。")
            return

    print("❌ 有効なセール商品が見つかりませんでした。")


def main():
    parser = argparse.ArgumentParser(description="X Selenium Setup & Test")
    parser.add_argument("--test", action="store_true", help="保存済みプロファイルを使って1件テスト投稿を行います")
    args = parser.parse_args()

    if args.test:
        test_single_post()
    else:
        login_session()


if __name__ == "__main__":
    main()
