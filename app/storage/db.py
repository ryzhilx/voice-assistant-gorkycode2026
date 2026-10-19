import sqlite3
import asyncio
from typing import List, Dict, Any, Optional

class Database:
    def __init__(self, db_path: str = "assistant.db"):
        self.db_path = db_path
        self._is_memory = (db_path == ":memory:")
        self._shared_conn: Optional[sqlite3.Connection] = None
        if not self._is_memory and self.db_path:
            import os
            dirname = os.path.dirname(self.db_path)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
        if self._is_memory:
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        timezone TEXT DEFAULT 'Europe/Moscow',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        due_date TEXT,
                        due_time TEXT,
                        is_reminder BOOLEAN DEFAULT 0,
                        reminder_sent BOOLEAN DEFAULT 0,
                        status TEXT DEFAULT 'pending',
                        recurrence TEXT DEFAULT NULL,
                        base_date TEXT DEFAULT NULL,
                        last_completed_date TEXT DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS meetings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        start_date TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        duration_minutes INTEGER DEFAULT 60,
                        participants TEXT,
                        reminder_sent BOOLEAN DEFAULT 0,
                        status TEXT DEFAULT 'active',
                        recurrence TEXT DEFAULT NULL,
                        base_date TEXT DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN reminder_sent BOOLEAN DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE meetings ADD COLUMN reminder_sent BOOLEAN DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE meetings ADD COLUMN status TEXT DEFAULT 'active'")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT DEFAULT NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE meetings ADD COLUMN recurrence TEXT DEFAULT NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN base_date TEXT DEFAULT NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE tasks ADD COLUMN last_completed_date TEXT DEFAULT NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE meetings ADD COLUMN base_date TEXT DEFAULT NULL")
                except sqlite3.OperationalError:
                    pass
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, due_date)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_user_date ON meetings(user_id, start_date)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_reminder ON tasks(reminder_sent, due_date, due_time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_reminder ON meetings(reminder_sent, start_date, start_time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(user_id, status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(user_id, status)")
        finally:
            if not self._is_memory:
                conn.close()

    @staticmethod
    def matches_recurrence(target_date, base_date, recurrence: Optional[str]) -> bool:
        if not recurrence:
            return False
        if base_date and target_date < base_date:
            return False

        rec = recurrence.lower().strip()
        if rec == "daily":
            return True
        if rec == "weekdays":
            return target_date.weekday() < 5
        if rec == "weekends":
            return target_date.weekday() >= 5
        if rec == "weekly":
            if not base_date:
                return target_date.weekday() == 0
            return target_date.weekday() == base_date.weekday()
        if rec.startswith("weekly:"):
            day_str = rec.split(":", 1)[1].strip()
            day_map = {
                "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
                "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6
            }
            target_weekday = day_map.get(day_str)
            if target_weekday is not None:
                return target_date.weekday() == target_weekday
            return False
        if rec == "monthly":
            if not base_date:
                return target_date.day == 1
            import calendar
            max_day = calendar.monthrange(target_date.year, target_date.month)[1]
            effective_day = min(base_date.day, max_day)
            return target_date.day == effective_day
        return False

    @staticmethod
    def calculate_next_occurrence(date_str: str, recurrence: str, from_date: Optional[str] = None) -> str:
        import datetime
        import calendar

        base_dt = datetime.date.fromisoformat(date_str)
        curr = base_dt
        limit_dt = datetime.date.fromisoformat(from_date) if from_date else base_dt

        rec = recurrence.lower().strip()

        if rec == "daily":
            curr = curr + datetime.timedelta(days=1)
            while curr <= limit_dt:
                curr += datetime.timedelta(days=1)
            return curr.isoformat()

        if rec == "weekdays":
            curr = curr + datetime.timedelta(days=1)
            while curr.weekday() >= 5 or curr <= limit_dt:
                curr += datetime.timedelta(days=1)
            return curr.isoformat()

        if rec == "weekends":
            curr = curr + datetime.timedelta(days=1)
            while curr.weekday() < 5 or curr <= limit_dt:
                curr += datetime.timedelta(days=1)
            return curr.isoformat()

        if rec == "weekly":
            curr = curr + datetime.timedelta(days=7)
            while curr <= limit_dt:
                curr += datetime.timedelta(days=7)
            return curr.isoformat()

        if rec.startswith("weekly:"):
            day_str = rec.split(":", 1)[1].strip()
            day_map = {
                "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
                "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6
            }
            target_weekday = day_map.get(day_str, 0)
            curr = curr + datetime.timedelta(days=1)
            while curr.weekday() != target_weekday or curr <= limit_dt:
                curr += datetime.timedelta(days=1)
            return curr.isoformat()

        if rec == "monthly":
            y = curr.year
            m = curr.month
            orig_day = base_dt.day
            while True:
                m += 1
                if m > 12:
                    m = 1
                    y += 1
                max_d = calendar.monthrange(y, m)[1]
                cand = datetime.date(y, m, min(orig_day, max_d))
                if cand > limit_dt and cand > base_dt:
                    return cand.isoformat()

        return (curr + datetime.timedelta(days=1)).isoformat()

    async def advance_recurring_task(self, task_id: int, next_date: str) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        UPDATE tasks
                        SET due_date = ?, reminder_sent = 0, status = 'pending'
                        WHERE id = ?
                        """,
                        (next_date, task_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def advance_recurring_meeting(self, meeting_id: int, next_date: str) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        UPDATE meetings
                        SET start_date = ?, reminder_sent = 0, status = 'active'
                        WHERE id = ?
                        """,
                        (next_date, meeting_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def add_task(
        self,
        user_id: int,
        title: str,
        due_date: Optional[str] = None,
        due_time: Optional[str] = None,
        is_reminder: bool = False,
        recurrence: Optional[str] = None
    ) -> int:
        def _insert():
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO tasks (user_id, title, due_date, due_time, is_reminder, recurrence, base_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, title, due_date, due_time, 1 if is_reminder else 0, recurrence, due_date)
                    )
                    return cursor.lastrowid
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_insert)

    async def add_meeting(
        self,
        user_id: int,
        title: str,
        start_date: str,
        start_time: str,
        duration_minutes: int = 60,
        participants: Optional[str] = None,
        recurrence: Optional[str] = None
    ) -> int:
        def _insert():
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO meetings (user_id, title, start_date, start_time, duration_minutes, participants, recurrence, base_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, title, start_date, start_time, duration_minutes, participants, recurrence, start_date)
                    )
                    return cursor.lastrowid
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_insert)

    async def check_meeting_conflict(
        self,
        user_id: int,
        start_date: str,
        start_time: str,
        exclude_id: Optional[int] = None,
        recurrence: Optional[str] = None,
        duration_minutes: int = 60
    ) -> Optional[Dict[str, Any]]:
        def _check():
            conn = self._get_connection()
            try:
                dur = duration_minutes or 60
                n_h, n_m = map(int, start_time.split(":", 1))
                n_start = n_h * 60 + n_m
                n_end = n_start + dur

                query = """
                    SELECT id, title, start_date, start_time, duration_minutes, recurrence
                    FROM meetings
                    WHERE user_id = ? AND (recurrence IS NULL OR recurrence = '') AND start_date = ? AND status != 'archived'
                """
                params = [user_id, start_date]
                if exclude_id is not None:
                    query += " AND id != ?"
                    params.append(exclude_id)
                rows = conn.execute(query, tuple(params)).fetchall()

                exact_match = None
                overlap_match = None
                for row in rows:
                    c_h, c_m = map(int, row["start_time"].split(":", 1))
                    c_dur = row["duration_minutes"] or 60
                    c_start = c_h * 60 + c_m
                    c_end = c_start + c_dur

                    if row["start_time"] == start_time:
                        exact_match = dict(row)
                        break
                    if n_start < c_end and n_end > c_start:
                        if not overlap_match:
                            overlap_match = dict(row)

                if exact_match:
                    return exact_match
                if overlap_match:
                    return overlap_match

                rec_query = """
                    SELECT id, title, start_date, start_time, duration_minutes, recurrence,
                           COALESCE(base_date, start_date, date(created_at)) as base_date
                    FROM meetings
                    WHERE user_id = ? AND recurrence IS NOT NULL AND recurrence != '' AND status != 'archived'
                """
                rec_params = [user_id]
                if exclude_id is not None:
                    rec_query += " AND id != ?"
                    rec_params.append(exclude_id)
                rec_rows = conn.execute(rec_query, tuple(rec_params)).fetchall()
                target_dt = None
                if start_date:
                    import datetime
                    target_dt = datetime.date.fromisoformat(start_date)

                if rec_rows and target_dt:
                    rec_exact = None
                    rec_overlap = None
                    for r in rec_rows:
                        base_d = datetime.date.fromisoformat(r["base_date"]) if r["base_date"] else None
                        if self.matches_recurrence(target_dt, base_d, r["recurrence"]):
                            c_h, c_m = map(int, r["start_time"].split(":", 1))
                            c_dur = r["duration_minutes"] or 60
                            c_start = c_h * 60 + c_m
                            c_end = c_start + c_dur
                            if r["start_time"] == start_time:
                                rec_exact = dict(r)
                                break
                            if n_start < c_end and n_end > c_start:
                                if not rec_overlap:
                                    rec_overlap = dict(r)
                    if rec_exact:
                        return rec_exact
                    if rec_overlap:
                        return rec_overlap

                if recurrence and target_dt:
                    all_meetings = conn.execute(
                        """
                        SELECT id, title, start_date, start_time, duration_minutes, recurrence,
                               COALESCE(base_date, start_date, date(created_at)) as base_date
                        FROM meetings
                        WHERE user_id = ? AND status != 'archived'
                        """,
                        (user_id,)
                    ).fetchall()
                    import datetime
                    for m in all_meetings:
                        if exclude_id is not None and m["id"] == exclude_id:
                            continue
                        m_rec = m["recurrence"]
                        c_h, c_m = map(int, m["start_time"].split(":", 1))
                        c_dur = m["duration_minutes"] or 60
                        c_start = c_h * 60 + c_m
                        c_end = c_start + c_dur
                        if not (n_start < c_end and n_end > c_start):
                            continue

                        if m_rec:
                            m_base = datetime.date.fromisoformat(m["base_date"]) if m["base_date"] else None
                            check_day = max(target_dt, m_base) if m_base else target_dt
                            for d_offset in range(30):
                                cand = check_day + datetime.timedelta(days=d_offset)
                                if self.matches_recurrence(cand, target_dt, recurrence) and self.matches_recurrence(cand, m_base, m_rec):
                                    return dict(m)
                        else:
                            m_date = datetime.date.fromisoformat(m["start_date"])
                            if self.matches_recurrence(m_date, target_dt, recurrence):
                                return dict(m)

                return None
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_check)

    async def archive_past_records(
        self,
        user_id: Optional[int] = None,
        current_date: Optional[str] = None,
        current_time: Optional[str] = None
    ) -> int:
        def _archive_user(conn, uid: int, c_date: str, c_time: str) -> int:
            count = 0
            cur1 = conn.execute(
                """
                UPDATE meetings
                SET status = 'archived', reminder_sent = 1
                WHERE user_id = ?
                  AND status != 'archived'
                  AND (recurrence IS NULL OR recurrence = '')
                  AND (
                      start_date < ?
                      OR (start_date = ? AND time(start_time, '+' || COALESCE(duration_minutes, 60) || ' minutes') <= time(?))
                  )
                """,
                (uid, c_date, c_date, c_time)
            )
            count += cur1.rowcount

            cur2 = conn.execute(
                """
                UPDATE tasks
                SET status = 'archived', reminder_sent = 1
                WHERE user_id = ?
                  AND status != 'archived'
                  AND is_reminder = 1
                  AND (recurrence IS NULL OR recurrence = '')
                  AND (
                      due_date < ?
                      OR (due_date = ? AND due_time IS NOT NULL AND due_time <= ? AND reminder_sent = 1)
                  )
                """,
                (uid, c_date, c_date, c_time)
            )
            count += cur2.rowcount

            cur3 = conn.execute(
                """
                UPDATE tasks
                SET status = 'archived'
                WHERE user_id = ?
                  AND status = 'completed'
                  AND (recurrence IS NULL OR recurrence = '')
                  AND (
                      due_date < ?
                      OR due_date IS NULL
                  )
                """,
                (uid, c_date)
            )
            count += cur3.rowcount
            return count

        def _run():
            import datetime
            conn = self._get_connection()
            total = 0
            try:
                with conn:
                    if user_id is not None:
                        tz_row = conn.execute("SELECT timezone FROM users WHERE user_id = ?", (user_id,)).fetchone()
                        tz_str = tz_row["timezone"] if tz_row and tz_row["timezone"] else "Europe/Moscow"
                        if current_date and current_time:
                            c_d, c_t = current_date, current_time
                        else:
                            try:
                                from zoneinfo import ZoneInfo
                                now_dt = datetime.datetime.now(ZoneInfo(tz_str))
                            except Exception:
                                now_dt = datetime.datetime.now()
                            c_d = now_dt.strftime("%Y-%m-%d")
                            c_t = now_dt.strftime("%H:%M")
                        total = _archive_user(conn, user_id, c_d, c_t)
                    else:
                        user_rows = conn.execute(
                            """
                            SELECT DISTINCT all_u.user_id, COALESCE(u.timezone, 'Europe/Moscow') as timezone
                            FROM (
                                SELECT user_id FROM users
                                UNION
                                SELECT user_id FROM meetings WHERE status != 'archived'
                                UNION
                                SELECT user_id FROM tasks WHERE status != 'archived'
                            ) all_u
                            LEFT JOIN users u ON all_u.user_id = u.user_id
                            """
                        ).fetchall()
                        for u in user_rows:
                            uid = u["user_id"]
                            tz_str = u["timezone"] or "Europe/Moscow"
                            try:
                                from zoneinfo import ZoneInfo
                                now_dt = datetime.datetime.now(ZoneInfo(tz_str))
                            except Exception:
                                now_dt = datetime.datetime.now()
                            c_d = now_dt.strftime("%Y-%m-%d")
                            c_t = now_dt.strftime("%H:%M")
                            total += _archive_user(conn, uid, c_d, c_t)
                return total
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_run)

    async def get_schedule(
        self,
        user_id: int,
        start_date: str,
        end_date: Optional[str] = None,
        filter_type: str = "all",
        include_archived: bool = False
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not end_date:
            end_date = start_date

        if not include_archived:
            tz_str = await self.get_user_timezone(user_id)
            import datetime
            try:
                from zoneinfo import ZoneInfo
                now_dt = datetime.datetime.now(ZoneInfo(tz_str))
            except Exception:
                now_dt = datetime.datetime.now()
            today_str = now_dt.strftime("%Y-%m-%d")
            c_d = min(today_str, start_date)
            c_t = now_dt.strftime("%H:%M") if c_d == today_str else "23:59"
            await self.archive_past_records(user_id=user_id, current_date=c_d, current_time=c_t)

        def _query():
            conn = self._get_connection()
            tasks = []
            meetings = []
            try:
                status_cond = "" if include_archived else "AND status != 'archived'"
                import datetime

                start_dt = datetime.date.fromisoformat(start_date)
                end_dt = datetime.date.fromisoformat(end_date)

                if filter_type in ("all", "tasks"):
                    rows = conn.execute(
                        f"""
                        SELECT id, title, due_date, due_time, is_reminder, status, recurrence
                        FROM tasks
                        WHERE user_id = ? AND (recurrence IS NULL OR recurrence = '') AND due_date BETWEEN ? AND ? {status_cond}
                        ORDER BY due_time ASC
                        """,
                        (user_id, start_date, end_date)
                    ).fetchall()
                    tasks = [dict(r) for r in rows]

                    rec_rows = conn.execute(
                        f"""
                        SELECT id, title, due_date, due_time, is_reminder, status, recurrence,
                               COALESCE(base_date, due_date, date(created_at)) as base_date,
                               last_completed_date
                        FROM tasks
                        WHERE user_id = ? AND recurrence IS NOT NULL AND recurrence != '' {status_cond}
                        ORDER BY due_time ASC
                        """,
                        (user_id,)
                    ).fetchall()

                    for r in rec_rows:
                        rec_dict = dict(r)
                        rec_val = rec_dict.get("recurrence")
                        base_d = datetime.date.fromisoformat(rec_dict["base_date"]) if rec_dict.get("base_date") else None

                        cur_day = start_dt
                        while cur_day <= end_dt:
                            if self.matches_recurrence(cur_day, base_d, rec_val):
                                item = dict(rec_dict)
                                cur_day_str = cur_day.isoformat()
                                item["due_date"] = cur_day_str
                                if rec_dict.get("last_completed_date") == cur_day_str:
                                    item["status"] = "completed"
                                elif rec_dict.get("due_date") and cur_day < datetime.date.fromisoformat(rec_dict["due_date"]):
                                    item["status"] = "completed"
                                else:
                                    item["status"] = rec_dict.get("status") or "pending"
                                tasks.append(item)
                            cur_day += datetime.timedelta(days=1)

                    tasks.sort(key=lambda x: (x.get("due_date") or "", x.get("due_time") or ""))

                if filter_type in ("all", "meetings"):
                    rows = conn.execute(
                        f"""
                        SELECT id, title, start_date, start_time, duration_minutes, participants, status, recurrence
                        FROM meetings
                        WHERE user_id = ? AND (recurrence IS NULL OR recurrence = '') AND start_date BETWEEN ? AND ? {status_cond}
                        ORDER BY start_time ASC
                        """,
                        (user_id, start_date, end_date)
                    ).fetchall()
                    meetings = [dict(r) for r in rows]

                    rec_rows = conn.execute(
                        f"""
                        SELECT id, title, start_date, start_time, duration_minutes, participants, status, recurrence,
                               COALESCE(base_date, start_date, date(created_at)) as base_date
                        FROM meetings
                        WHERE user_id = ? AND recurrence IS NOT NULL AND recurrence != '' {status_cond}
                        ORDER BY start_time ASC
                        """,
                        (user_id,)
                    ).fetchall()

                    for r in rec_rows:
                        rec_dict = dict(r)
                        rec_val = rec_dict.get("recurrence")
                        base_d = datetime.date.fromisoformat(rec_dict["base_date"]) if rec_dict.get("base_date") else None

                        cur_day = start_dt
                        while cur_day <= end_dt:
                            if self.matches_recurrence(cur_day, base_d, rec_val):
                                item = dict(rec_dict)
                                item["start_date"] = cur_day.isoformat()
                                meetings.append(item)
                            cur_day += datetime.timedelta(days=1)

                    meetings.sort(key=lambda x: (x.get("start_date") or "", x.get("start_time") or ""))

                return {"tasks": tasks, "meetings": meetings}
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def get_archive(
        self,
        user_id: int,
        filter_type: str = "all",
        limit: int = 20
    ) -> Dict[str, List[Dict[str, Any]]]:
        def _query():
            conn = self._get_connection()
            try:
                meetings = []
                tasks = []
                if filter_type in ("all", "meetings"):
                    rows = conn.execute(
                        """
                        SELECT id, title, start_date, start_time, duration_minutes, participants, status
                        FROM meetings
                        WHERE user_id = ? AND status = 'archived'
                        ORDER BY start_date DESC, start_time DESC
                        LIMIT ?
                        """,
                        (user_id, limit)
                    ).fetchall()
                    meetings = [dict(m) for m in rows]

                if filter_type in ("all", "tasks"):
                    rows = conn.execute(
                        """
                        SELECT id, title, due_date, due_time, is_reminder, status
                        FROM tasks
                        WHERE user_id = ? AND status IN ('archived', 'completed')
                        ORDER BY COALESCE(due_date, date(created_at)) DESC, due_time DESC
                        LIMIT ?
                        """,
                        (user_id, limit)
                    ).fetchall()
                    tasks = [dict(t) for t in rows]

                return {
                    "meetings": meetings,
                    "tasks": tasks
                }
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def archive_record(self, user_id: int, record_type: str, record_id: int) -> bool:
        def _update():
            conn = self._get_connection()
            table = "meetings" if record_type in ("meeting", "meetings") else "tasks"
            try:
                with conn:
                    cur = conn.execute(
                        f"UPDATE {table} SET status = 'archived' WHERE id = ? AND user_id = ?",
                        (record_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def restore_record(self, user_id: int, record_type: str, record_id: int) -> bool:
        def _update():
            conn = self._get_connection()
            table = "meetings" if record_type in ("meeting", "meetings") else "tasks"
            new_status = "active" if record_type in ("meeting", "meetings") else "pending"
            try:
                with conn:
                    cur = conn.execute(
                        f"UPDATE {table} SET status = ? WHERE id = ? AND user_id = ?",
                        (new_status, record_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def get_all_records_for_search(self, user_id: int, record_type: str = "all") -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            records = []
            try:
                if record_type in ("all", "tasks"):
                    rows = conn.execute(
                        "SELECT id, title, due_date as date, due_time as time, status, 'task' as type, recurrence FROM tasks WHERE user_id = ?",
                        (user_id,)
                    ).fetchall()
                    records.extend([dict(r) for r in rows])

                if record_type in ("all", "meetings"):
                    rows = conn.execute(
                        "SELECT id, title, start_date as date, start_time as time, status, 'meeting' as type, participants, recurrence FROM meetings WHERE user_id = ?",
                        (user_id,)
                    ).fetchall()
                    records.extend([dict(r) for r in rows])

                return records
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def mark_task_completed(self, user_id: int, task_id: int) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    row = conn.execute(
                        "SELECT due_date, recurrence, last_completed_date FROM tasks WHERE id = ? AND user_id = ?",
                        (task_id, user_id)
                    ).fetchone()
                    if not row:
                        return False

                    if row["recurrence"]:
                        import datetime
                        tz_row = conn.execute("SELECT timezone FROM users WHERE user_id = ?", (user_id,)).fetchone()
                        tz_str = tz_row["timezone"] if tz_row and tz_row["timezone"] else "Europe/Moscow"
                        try:
                            from zoneinfo import ZoneInfo
                            today_str = datetime.datetime.now(ZoneInfo(tz_str)).date().isoformat()
                        except Exception:
                            today_str = datetime.date.today().isoformat()

                        due = row["due_date"] or today_str
                        if due < today_str:
                            next_date = self.calculate_next_occurrence(due, row["recurrence"])
                            while next_date < today_str:
                                next_date = self.calculate_next_occurrence(next_date, row["recurrence"])
                            cur = conn.execute(
                                """
                                UPDATE tasks
                                SET due_date = ?, reminder_sent = 0, status = 'pending', last_completed_date = ?
                                WHERE id = ? AND user_id = ?
                                """,
                                (next_date, due, task_id, user_id)
                            )
                        elif due == today_str:
                            if row["last_completed_date"] == today_str:
                                return True
                            next_date = self.calculate_next_occurrence(due, row["recurrence"], from_date=today_str)
                            cur = conn.execute(
                                """
                                UPDATE tasks
                                SET due_date = ?, reminder_sent = 0, status = 'pending', last_completed_date = ?
                                WHERE id = ? AND user_id = ?
                                """,
                                (next_date, today_str, task_id, user_id)
                            )
                        else:
                            if row["last_completed_date"] == today_str:
                                return True
                            cur = conn.execute(
                                """
                                UPDATE tasks
                                SET last_completed_date = ?
                                WHERE id = ? AND user_id = ?
                                """,
                                (today_str, task_id, user_id)
                            )
                        return cur.rowcount > 0

                    cur = conn.execute(
                        "UPDATE tasks SET status = 'completed' WHERE id = ? AND user_id = ?",
                        (task_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def update_meeting_time(
        self,
        user_id: int,
        meeting_id: int,
        start_date: str,
        start_time: str
    ) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        UPDATE meetings
                        SET start_date = ?, start_time = ?, base_date = ?, reminder_sent = 0, status = 'active'
                        WHERE id = ? AND user_id = ?
                        """,
                        (start_date, start_time, start_date, meeting_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def update_task_time(
        self,
        user_id: int,
        task_id: int,
        due_date: Optional[str] = None,
        due_time: Optional[str] = None
    ) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        UPDATE tasks
                        SET due_date = COALESCE(?, due_date),
                            due_time = COALESCE(?, due_time),
                            base_date = COALESCE(?, base_date),
                            reminder_sent = 0,
                            status = 'pending'
                        WHERE id = ? AND user_id = ?
                        """,
                        (due_date, due_time, due_date, task_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def get_latest_record(self, user_id: int, record_type: str = "last") -> Optional[Dict[str, Any]]:
        def _get():
            conn = self._get_connection()
            try:
                if record_type in ("meeting", "meetings"):
                    row = conn.execute(
                        """
                        SELECT id, title, start_date as date, start_time as time, status, 'meeting' as type, recurrence
                        FROM meetings
                        WHERE user_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (user_id,)
                    ).fetchone()
                    return dict(row) if row else None

                if record_type in ("task", "tasks"):
                    row = conn.execute(
                        """
                        SELECT id, title, due_date as date, due_time as time, status, 'task' as type, recurrence
                        FROM tasks
                        WHERE user_id = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (user_id,)
                    ).fetchone()
                    return dict(row) if row else None

                m_row = conn.execute(
                    """
                    SELECT id, title, start_date as date, start_time as time, status, 'meeting' as type, created_at, recurrence
                    FROM meetings
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (user_id,)
                ).fetchone()

                t_row = conn.execute(
                    """
                    SELECT id, title, due_date as date, due_time as time, status, 'task' as type, created_at, recurrence
                    FROM tasks
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (user_id,)
                ).fetchone()

                if m_row and t_row:
                    if str(m_row["created_at"]) >= str(t_row["created_at"]):
                        return dict(m_row)
                    return dict(t_row)
                if m_row:
                    return dict(m_row)
                if t_row:
                    return dict(t_row)
                return None
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_get)

    async def delete_record(self, user_id: int, record_type: str, record_id: int) -> bool:
        def _del():
            conn = self._get_connection()
            table = "meetings" if record_type in ("meeting", "meetings") else "tasks"
            try:
                with conn:
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE id = ? AND user_id = ?",
                        (record_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_del)

    async def update_record_title(self, user_id: int, record_type: str, record_id: int, new_title: str) -> bool:
        def _upd():
            conn = self._get_connection()
            table = "meetings" if record_type in ("meeting", "meetings") else "tasks"
            try:
                with conn:
                    cur = conn.execute(
                        f"UPDATE {table} SET title = ? WHERE id = ? AND user_id = ?",
                        (new_title, record_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_upd)

    async def get_due_tasks(self, current_date: Optional[str] = None, current_time: Optional[str] = None) -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            try:
                base_sql = """
                    SELECT t.id, t.user_id, t.title, t.due_date, t.due_time, t.is_reminder, t.recurrence,
                           COALESCE(u.timezone, 'Europe/Moscow') as timezone
                    FROM tasks t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    WHERE t.status NOT IN ('completed', 'archived')
                      AND t.reminder_sent = 0
                      AND t.due_date IS NOT NULL
                      AND t.due_time IS NOT NULL
                """
                if current_date and current_time:
                    base_sql += """
                      AND (
                          (t.due_date = ? AND t.due_time <= ?)
                          OR (t.due_date < ?)
                      )
                    """
                    rows = conn.execute(base_sql + " ORDER BY t.due_date ASC, t.due_time ASC", (current_date, current_time, current_date)).fetchall()
                else:
                    rows = conn.execute(base_sql + " ORDER BY t.due_date ASC, t.due_time ASC").fetchall()
                return [dict(r) for r in rows]
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def mark_task_reminder_sent(self, task_id: int) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        "UPDATE tasks SET reminder_sent = 1 WHERE id = ?",
                        (task_id,)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def get_due_meetings(self, current_date: Optional[str] = None, current_time: Optional[str] = None) -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            try:
                base_sql = """
                    SELECT m.id, m.user_id, m.title, m.start_date, m.start_time, m.duration_minutes, m.participants, m.recurrence,
                           COALESCE(u.timezone, 'Europe/Moscow') as timezone
                    FROM meetings m
                    LEFT JOIN users u ON m.user_id = u.user_id
                    WHERE m.reminder_sent = 0
                      AND m.status != 'archived'
                      AND m.start_date IS NOT NULL
                      AND m.start_time IS NOT NULL
                """
                if current_date and current_time:
                    base_sql += """
                      AND (
                          (m.start_date = ? AND m.start_time <= ?)
                          OR (m.start_date < ?)
                      )
                    """
                    rows = conn.execute(base_sql + " ORDER BY m.start_date ASC, m.start_time ASC", (current_date, current_time, current_date)).fetchall()
                else:
                    rows = conn.execute(base_sql + " ORDER BY m.start_date ASC, m.start_time ASC").fetchall()
                return [dict(r) for r in rows]
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def mark_meeting_reminder_sent(self, meeting_id: int) -> bool:
        def _update():
            conn = self._get_connection()
            try:
                with conn:
                    cur = conn.execute(
                        "UPDATE meetings SET reminder_sent = 1 WHERE id = ?",
                        (meeting_id,)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def get_user_timezone(self, user_id: int) -> str:
        def _get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT timezone FROM users WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                return row["timezone"] if row and row["timezone"] else "Europe/Moscow"
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_get)

    async def set_user_timezone(self, user_id: int, timezone: str, username: Optional[str] = None) -> None:
        def _set():
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO users (user_id, username, timezone)
                        VALUES (?, ?, ?)
                        ON CONFLICT(user_id) DO UPDATE SET
                            timezone = excluded.timezone,
                            username = COALESCE(excluded.username, users.username)
                        """,
                        (user_id, username, timezone)
                    )
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_set)
