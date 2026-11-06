"""投递队列：租约 + 每日上限 + 指数退避 + 死信。崩溃后靠 lease 自动回收。"""
from __future__ import annotations

import time

BACKOFF = (60, 300, 900, 3600)


class Queue:
    def __init__(self, store, daily_cap: int = 15, lease: int = 300):
        self.s, self.cap, self.lease = store, daily_cap, lease

    # ---------- 入队 ----------
    def enqueue(self, job_id: str, score: float) -> bool:
        r = self.s.db.execute("select state from apps where job_id=?", (job_id,)).fetchone()
        if r:  # 幂等：已经在队列或已投过，绝不重复
            return False
        self.s.db.execute(
            "insert into apps(job_id,state,score,attempts,next_at,lease_until,ts,note)"
            " values(?,?,?,0,0,0,?,'')", (job_id, "queued", score, time.time()))
        self.s.db.commit()
        self.s.log("queue.enqueue", job_id, {"score": score})
        return True

    def submitted_today(self, now: float | None = None) -> int:
        """今天已经"动过手"的条数：被领走/已填/已投都算，防止无限领任务。"""
        day = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        return self.s.db.execute(
            "select count(*) from apps where state in ('filling','filled','submitted')"
            " and date(ts,'unixepoch','localtime')=?", (day,)).fetchone()[0]

    # ---------- 领取 ----------
    def claim(self, now: float | None = None):
        now = now or time.time()
        if self.submitted_today(now) >= self.cap:
            self.s.log("queue.capped", "", {"cap": self.cap})
            return None
        row = self.s.db.execute(
            "select * from apps where state in ('queued','filling') and next_at<=?"
            " and lease_until<=? order by score desc limit 1", (now, now)).fetchone()
        if not row:
            return None
        self.s.db.execute(
            "update apps set state='filling', lease_until=?, ts=?"
            " where job_id=?", (now + self.lease, now, row["job_id"]))
        self.s.db.commit()
        self.s.log("queue.claim", row["job_id"], {"attempts": row["attempts"]})
        return dict(row)

    # ---------- 推进 ----------
    def mark(self, job_id: str, state: str, note: str = "") -> None:
        assert state in ("queued", "filling", "filled", "submitted", "replied",
                         "interview", "rejected", "dead"), state
        self.s.db.execute(
            "update apps set state=?, lease_until=0, note=?, ts=? where job_id=?",
            (state, note, time.time(), job_id))
        self.s.db.commit()
        self.s.log("queue." + state, job_id, {"note": note})

    def fail(self, job_id: str, err: str):
        row = self.s.db.execute("select attempts from apps where job_id=?",
                                (job_id,)).fetchone()
        if not row:
            return
        n = row["attempts"] + 1
        if n > len(BACKOFF):
            self.s.db.execute(
                "update apps set state='dead', attempts=?, lease_until=0, note=?, ts=?"
                " where job_id=?", (n, err[:200], time.time(), job_id))
            self.s.db.commit()
            self.s.log("queue.dead", job_id, {"attempts": n, "err": err[:120]})
            return
        wait = BACKOFF[min(n - 1, len(BACKOFF) - 1)]
        self.s.db.execute(
            "update apps set state='queued', attempts=?, next_at=?, lease_until=0,"
            " note=?, ts=? where job_id=?",
            (n, time.time() + wait, err[:200], time.time(), job_id))
        self.s.db.commit()
        self.s.log("queue.retry", job_id, {"in": wait, "err": err[:120]})

    # ---------- 观测 ----------
    def snapshot(self) -> dict:
        rows = self.s.db.execute(
            "select state, count(*) n from apps group by state").fetchall()
        return {"by_state": {r["state"]: r["n"] for r in rows},
                "submitted_today": self.submitted_today(), "cap": self.cap}
