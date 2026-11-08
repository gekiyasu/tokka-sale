"""
X 投稿の安全装置 (凍結・制限リスクの低減)

- 投稿可能時間帯 (JST) の制限
- 1日の投稿上限 (アカウント作成直後は少なく始めて段階的に増やすウォームアップ)
- 投稿間隔の確保 (ランダムな揺らぎ付き)
- 失敗が続いた場合 / ログイン要求・アカウントロストを検知した場合の自動停止 (サーキットブレーカー)

状態は deals_history.db の x_state / x_log テーブルに保存する。
注意: これはリスクを下げる仕組みであり、凍結・制限が起きないことを保証するものではない。
"""
import logging
import random
import sqlite3
from datetime import datetime, timedelta, timezone

from db import DB_PATH

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# --- 設定 (必要なら調整) ---
ACTIVE_HOUR_START = 8      # JST 8:00 から
ACTIVE_HOUR_END = 23       # JST 23:00 まで (23:00 以降は投稿しない)
BASE_GAP_MINUTES = 120     # 基本の投稿間隔
GAP_JITTER = (0.8, 1.6)    # 間隔の揺らぎ倍率
FAIL_BREAKER_COUNT = 3     # 連続失敗でストップ
FAIL_PAUSE_HOURS = 6
LOCK_PAUSE_HOURS = 48      # ロック/確認要求を検知した場合の停止時間

# ウォームアップ: (経過日数の上限, 1日の投稿上限)
WARMUP = [(3, 2), (7, 4), (14, 6)]
FINAL_DAILY_LIMIT = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


class XGuard:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS x_state (k TEXT PRIMARY KEY, v TEXT)")
            c.execute(
                "CREATE TABLE IF NOT EXISTS x_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL)"
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _get(self, key):
        with self._conn() as c:
            r = c.execute("SELECT v FROM x_state WHERE k=?", (key,)).fetchone()
        return r[0] if r else None

    def _set(self, key, value):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO x_state (k, v) VALUES (?, ?)", (key, value))

    # --- 判定 ---
    def daily_limit(self) -> int:
        first = self._get("first_post_at")
        if not first:
            return WARMUP[0][1]
        days = (_now() - _parse(first)).days
        for max_days, limit in WARMUP:
            if days < max_days:
                return limit
        return FINAL_DAILY_LIMIT

    def _posts_last_24h(self) -> int:
        since = _iso(_now() - timedelta(hours=24))
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM x_log WHERE kind='post' AND ts>=?", (since,)).fetchone()[0]

    def check(self):
        """(投稿してよいか, 理由) を返す"""
        now = _now()
        paused = self._get("paused_until")
        if paused and now < _parse(paused):
            return False, f"自動停止中 (解除: {_parse(paused).astimezone(JST):%m/%d %H:%M} JST / 理由: {self._get('pause_reason')})"

        hour = now.astimezone(JST).hour
        if not (ACTIVE_HOUR_START <= hour < ACTIVE_HOUR_END):
            return False, f"投稿時間帯外 ({ACTIVE_HOUR_START}:00-{ACTIVE_HOUR_END}:00 JSTのみ投稿)"

        limit = self.daily_limit()
        n = self._posts_last_24h()
        if n >= limit:
            return False, f"24時間の投稿上限に到達 ({n}/{limit})"

        nxt = self._get("next_allowed_at")
        if nxt and now < _parse(nxt):
            return False, f"投稿間隔待ち (次回可能: {_parse(nxt).astimezone(JST):%H:%M} JST)"
        return True, "OK"

    # --- 記録 ---
    def record_success(self):
        now = _now()
        with self._conn() as c:
            c.execute("INSERT INTO x_log (ts, kind) VALUES (?, 'post')", (_iso(now),))
        if not self._get("first_post_at"):
            self._set("first_post_at", _iso(now))
        gap = BASE_GAP_MINUTES * random.uniform(*GAP_JITTER)
        self._set("next_allowed_at", _iso(now + timedelta(minutes=gap)))
        logger.info(f"[XGuard] 次回投稿可能: 約{int(gap)}分後 / 24h内 {self._posts_last_24h()}/{self.daily_limit()}件")

    def record_failure(self):
        with self._conn() as c:
            c.execute("INSERT INTO x_log (ts, kind) VALUES (?, 'fail')", (_iso(_now()),))
            rows = c.execute("SELECT kind FROM x_log ORDER BY id DESC LIMIT ?", (FAIL_BREAKER_COUNT,)).fetchall()
        if len(rows) == FAIL_BREAKER_COUNT and all(r[0] == "fail" for r in rows):
            self.pause(FAIL_PAUSE_HOURS, f"{FAIL_BREAKER_COUNT}回連続で投稿に失敗")

    def pause(self, hours: float, reason: str):
        until = _now() + timedelta(hours=hours)
        self._set("paused_until", _iso(until))
        self._set("pause_reason", reason)
        logger.error(f"🛑 [XGuard] X投稿を {hours}時間 停止します: {reason}")
