"""専用プロファイルでログイン中のXアカウント(@ハンドル)を表示する"""
import re
import time
from selenium.webdriver.common.by import By
from publisher import XPublisher


def main():
    pub = XPublisher()
    driver = pub._create_driver()
    try:
        driver.get("https://x.com/home")
        time.sleep(6)
        if "login" in driver.current_url or "flow" in driver.current_url:
            print("❌ 未ログインです。python setup_x_login.py を実行してください。")
            return
        try:
            btn = driver.find_element(By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"]')
            text = btn.text.replace("\n", " ")
            m = re.search(r"@\w+", text)
            print("✅ ログイン中のアカウント:", m.group(0) if m else text)
        except Exception:
            print("⚠️ アカウント名を取得できませんでした。URL:", driver.current_url)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
