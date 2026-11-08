import sqlite3
from db import Database

c = sqlite3.connect('deals_history.db')
print(c.execute("select datetime('now'), count(distinct asin), min(posted_at), max(posted_at) from posted_deals").fetchall())
print(c.execute("select substr(posted_at,1,13), count(*) from posted_deals group by 1 order by 1").fetchall())
print(len(Database().get_recent_deals(200, 14)), len(Database().get_recent_deals(200)))
