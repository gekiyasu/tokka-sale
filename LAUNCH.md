# 公開・X運用開始チェックリスト

## 0. 済み（準備作業）
- [x] `.env` / `deals_history.db` / `__pycache__` を git のステージから除外（`.gitignore` 対象なのに誤ってステージされていた。未コミットなので履歴には残っていない）
- [x] まとめサイトにアソシエイト開示文（PR表記）あり

## 1. Webサイト公開 (GitHub Pages)
1. GitHubで新規リポジトリ作成（公開リポジトリ。`.env` は絶対にpushしない）
2. ```bash
   git add -A
   git status        # .env / chrome_profile_x / *.db が含まれていないことを必ず確認
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<user>/<repo>.git
   git push -u origin main
   ```
3. GitHub: Settings → Pages → Source: `main` / `/docs`
4. 公開URL（`https://<user>.github.io/<repo>`）を `.env` の `SITE_BASE_URL` に設定
5. 手動でpushが成功し、サイトが表示されたら `AUTO_GIT_PUSH=true` に変更

## 2. X運用開始
1. `.env`: `ENABLE_X=true` / `X_USE_SELENIUM=true`
2. `python setup_x_login.py` で専用Chromeにログイン
3. `python setup_x_login.py --test` でテスト投稿
4. `python main.py --once` で1回実行 → 投稿内容とリンク先を確認
5. 問題なければ `python main.py` で常駐

## 3. 公開前に確認したい項目（要判断）
- アソシエイトID（`AMAZON_ASSOCIATE_TAG`）が本物か（現状 default の可能性）
- Amazonアソシエイト規約: 価格表示は取得時刻の明記が必要。X投稿には「#PR」等の広告表記を推奨
- Xの自動化ルール: Selenium自動投稿はアカウント制限リスクあり。投稿頻度は控えめに（`CHECK_INTERVAL_MINUTES`）。公式API利用が安全
- プライバシーポリシー・お問い合わせページ（任意だが推奨）
