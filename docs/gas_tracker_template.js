/**
 * Amazonセール通知Bot - クリック自動計測 ＆ 学習同期用 Google Apps Script (GAS) テンプレート
 * 
 * 【セットアップ手順 (約2分・完全無料)】
 * 1. Google ドライブで「新規」>「Google スプレッドシート」を作成（名前例: Amazonセールクリックログ）。
 * 2. 上部メニュー「拡張機能」>「Apps Script」をクリック。
 * 3. エディタにこのコードをすべて貼り付けて保存（Ctrl+S）。
 * 4. 初回のみ、エディタ上部で「setupSheet」関数を選択して「実行」ボタンを押す（シートのヘッダーが自動生成されます）。
 * 5. 右上「デプロイ」>「新しいデプロイ」をクリック：
 *    - 種類の選択:「ウェブアプリ」
 *    - 次のユーザーとして実行:「自分」
 *    - アクセスできるユーザー:「全員 (Anyone)」※重要
 * 6. 発行された「ウェブアプリ URL (https://script.google.com/macros/s/.../exec)」をコピー。
 * 7. 本プロジェクトの `.env` ファイルに以下を追記するだけ！
 *    CLICK_TRACKER_URL=https://script.google.com/macros/s/.../exec
 */

function setupSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("ClickLogs");
  if (!sheet) {
    sheet = ss.insertSheet("ClickLogs");
    sheet.appendRow(["タイムスタンプ(JST)", "ASIN", "カテゴリ", "ボタン種類", "価格", "割引率", "リファラ", "同期済みフラグ"]);
    sheet.getRange(1, 1, 1, 8).setBackground("#0f172a").setFontColor("#ffffff").setFontWeight("bold");
    sheet.setFrozenRows(1);
  }
}

// 1. クッションページ (GitHub Pages) からのクリック送信を受信 (POST)
function doPost(e) {
  try {
    const sheet = getOrCreateSheet();
    let data = {};
    if (e.postData && e.postData.contents) {
      try {
        data = JSON.parse(e.postData.contents);
      } catch (err) {
        data = e.parameter || {};
      }
    } else {
      data = e.parameter || {};
    }

    const nowJst = Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd HH:mm:ss");
    const asin = String(data.asin || "").trim();
    const category = String(data.category || "その他").trim();
    const btn = String(data.btn || "main_button").trim();
    const price = Number(data.price || 0);
    const discount = Number(data.discount || 0);
    const referrer = String(data.referrer || "").slice(0, 200);

    if (asin) {
      sheet.appendRow([nowJst, asin, category, btn, price, discount, referrer, "0"]);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "success", asin: asin }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: error.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// 2. Python Bot 側からの定期同期リクエストに応答 (GET)
// 直近の未同期ログ、または直近7日以内のクリックログをJSON形式で返却
function doGet(e) {
  try {
    const sheet = getOrCreateSheet();
    const data = sheet.getDataRange().getValues();
    if (data.length <= 1) {
      return ContentService.createTextOutput(JSON.stringify({ clicks: [] }))
        .setMimeType(ContentService.MimeType.JSON);
    }

    const clicks = [];
    // 直近最大500件を抽出
    const startRow = Math.max(1, data.length - 500);
    for (let i = startRow; i < data.length; i++) {
      const row = data[i];
      clicks.push({
        clicked_at: String(row[0]),
        asin: String(row[1]),
        category: String(row[2]),
        btn: String(row[3]),
        price: Number(row[4] || 0),
        discount: Number(row[5] || 0),
        referrer: String(row[6] || "")
      });
    }

    return ContentService.createTextOutput(JSON.stringify({ clicks: clicks }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({ error: error.toString(), clicks: [] }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function getOrCreateSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("ClickLogs");
  if (!sheet) {
    setupSheet();
    sheet = ss.getSheetByName("ClickLogs");
  }
  return sheet;
}
