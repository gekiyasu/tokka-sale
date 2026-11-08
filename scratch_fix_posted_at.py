"""posted_at が NULL になっている行の日時を補正する (一度きりの修復スクリプト)"""
import random
import sqlite3

from db import Database

db = Database()
conn = sqlite3.connect('deals_history.db')
ids = [r[0] for r in conn.execute("SELECT id FROM posted_deals WHERE posted_at IS NULL ORDER BY id").fetchall()]
for i in ids:
    offset = random.randint(25 * 60, 25 * 60 + 600)  # 25〜35時間前
    conn.execute("UPDATE posted_deals SET posted_at = datetime('now', ?) WHERE id = ?", (f"-{offset} minutes", i))
conn.commit()
print("補正:", len(ids), "件")
print("掲載対象:", len(db.get_recent_deals(200, 14)), "件")

from config import config
config.auto_git_push = False
from site_generator import SiteGenerator
SiteGenerator(db).build_site()
