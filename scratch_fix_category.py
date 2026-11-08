"""既存DBのカテゴリ表記ゆれを統一し、サイトをローカル再生成する (一度きりの修復スクリプト)"""
import sqlite3
from collections import Counter

from db import Database, normalize_category

db = Database()
conn = sqlite3.connect('deals_history.db')
rows = conn.execute("SELECT id, category, title FROM posted_deals").fetchall()
before = Counter(r[1] for r in rows)
for i, cat, title in rows:
    new = normalize_category(cat, title or "")
    if new != cat:
        conn.execute("UPDATE posted_deals SET category = ? WHERE id = ?", (new, i))
conn.commit()
after = Counter(r[0] for r in conn.execute("SELECT category FROM posted_deals").fetchall())
print("修正前:", dict(before))
print("修正後:", dict(after))

from config import config
config.auto_git_push = False
from site_generator import SiteGenerator
SiteGenerator(db).build_site()
other = [(r[0][:30], r[1]) for r in conn.execute("SELECT title, category FROM posted_deals WHERE category='その他' GROUP BY asin").fetchall()]
print("その他:", other)
