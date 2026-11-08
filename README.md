# Amazon セール自動検知＆マルチSNSアフィリエイトボット

Amazonの急激な値下げやタイムセール特価品を自動検知し、アフィリエイトリンクを付与して各SNS（X / Discord / Telegram / Bluesky）に完全自動投稿するシステムです。

---

## 主な機能

1. **セール・値下げの自動検知**
   - Keepa Deals API経由でAmazon.co.jpの最新特価品を自動収集。
   - APIキー未設定時はデモ用モックデータでテスト動作可能。
2. **スマートフィルタリング**
   - 「値下げ率（例: 20%以上OFF）」「星評価（例: 3.8以上）」「レビュー件数（例: 10件以上）」で絞り込み。
3. **重複投稿防止（SQLite内蔵）**
   - 過去24時間以内に投稿した商品は自動でスキップ。スパム判定を防ぎます。
4. **マルチSNS一括配信**
   - **X (旧Twitter)**: Selenium ブラウザ自動操作による画像＋アフィリエイトリンク付き自動ポスト（API課金不要・API v2 モードも選択可）
   - **Discord**: Webhookによる埋め込み画像付きリッチカード送信
   - **Telegram**: Bot APIによるチャンネル/グループへの即時通知
   - **Bluesky**: AT Protocolによる商品画像付きリンクカード投稿
   - 設定で有効化（`true`）にしたSNSにだけ自動配信されます。

---

## ディレクトリ構成

```
C:/VScode/Amazonセール通知/
├── .env.example          # 環境変数設定サンプル
├── config.py             # 設定値ローダー
├── db.py                 # SQLite重複管理
├── deals_tracker.py      # セール検知・API連携
├── models.py             # 商品・投稿フォーマットデータモデル
├── publisher.py          # 各SNS投稿ドライバー (Bluesky / X Selenium 等)
├── setup_x_login.py      # X (Selenium) 初回ログイン＆テスト投稿スクリプト
├── main.py               # メイン定期実行スクリプト
└── requirements.txt      # 依存パッケージ一覧
```

---

## セットアップ手順

### 1. 依存ライブラリのインストール

```bash
cd C:\VScode\Amazonセール通知
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env.example` をコピーして `.env` を作成し、各キーを設定します。

```bash
cp .env.example .env
```

`.env` 内の設定項目例：
- `AMAZON_ASSOCIATE_TAG`: あなたのAmazonアソシエイトID（例: `yourid-22`）
- `KEEPA_API_KEY`: [Keepa API](https://keepa.com/) のキー（有料プランでDeal APIが利用可能）
- `ENABLE_X=true` / `X_USE_SELENIUM=true`（SeleniumでXに無料自動投稿）
- `ENABLE_DISCORD=true` / `DISCORD_WEBHOOK_URL`
- `ENABLE_TELEGRAM=true` / `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `ENABLE_BLUESKY=true` / `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`

### 3. X (Selenium) の初回ログイン設定

Xへの自動投稿を有効にする場合、初回のみ専用Chromeプロファイルでログインを行います：

```bash
python setup_x_login.py
```

ログイン完了後、以下のコマンドで1件テスト投稿が行えます：

```bash
python setup_x_login.py --test
```

---

## 実行方法

### 動作テスト（1回のみ実行 & デモ出力）
まずはコンソール上で投稿内容を確認したい場合：
```bash
python main.py --once
```
過去に投稿済みの判定を無視して強制的にプレビュー表示したい場合：
```bash
python main.py --force
```
※SNSが無効（`false`）の場合は、投稿予定のテキストがコンソールにプレビュー表示されます。

### 本番定期実行
常駐して設定インターバル（デフォルト30分ごと）で巡回投稿する場合：
```bash
python main.py
```
