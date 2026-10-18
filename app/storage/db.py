import sqlite3
import asyncio
from typing import List, Dict, Any, Optional

class Database:
    def __init__(self, db_path: str = "assistant.db"):
        self.db_path = db_path
        self._is_memory = (db_path == ":memory:")
        self._shared_conn: Optional[sqlite3.Connection] = None
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
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, due_date)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_user_date ON meetings(user_id, start_date)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_reminder ON tasks(reminder_sent, due_date, due_time)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_reminder ON meetings(reminder_sent, start_date, start_time)")
        finally:
            if not self._is_memory:
                conn.close()

    async def add_task(
        self,
        user_id: int,
        title: str,
        due_date: Optional[str] = None,
        due_time: Optional[str] = None,
        is_reminder: bool = False
    ) -> int:
        def _insert():
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO tasks (user_id, title, due_date, due_time, is_reminder)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (user_id, title, due_date, due_time, 1 if is_reminder else 0)
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
        participants: Optional[str] = None
    ) -> int:
        def _insert():
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO meetings (user_id, title, start_date, start_time, duration_minutes, participants)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, title, start_date, start_time, duration_minutes, participants)
                    )
                    return cursor.lastrowid
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_insert)

    async def check_meeting_conflict(self, user_id: int, start_date: str, start_time: str) -> Optional[Dict[str, Any]]:
        def _check():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    """
                    SELECT id, title, start_date, start_time
                    FROM meetings
                    WHERE user_id = ? AND start_date = ? AND start_time = ?
                    LIMIT 1
                    """,
                    (user_id, start_date, start_time)
                ).fetchone()
                return dict(row) if row else None
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_check)

    async def get_schedule(
        self,
        user_id: int,
        start_date: str,
        end_date: Optional[str] = None,
        filter_type: str = "all"
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not end_date:
            end_date = start_date

        def _query():
            conn = self._get_connection()
            tasks = []
            meetings = []
            try:
                if filter_type in ("all", "tasks"):
                    rows = conn.execute(
                        """
                        SELECT id, title, due_date, due_time, is_reminder, status
                        FROM tasks
                        WHERE user_id = ? AND due_date BETWEEN ? AND ?
                        ORDER BY due_time ASC
                        """,
                        (user_id, start_date, end_date)
                    ).fetchall()
                    tasks = [dict(r) for r in rows]

                if filter_type in ("all", "meetings"):
                    rows = conn.execute(
                        """
                        SELECT id, title, start_date, start_time, duration_minutes, participants
                        FROM meetings
                        WHERE user_id = ? AND start_date BETWEEN ? AND ?
                        ORDER BY start_time ASC
                        """,
                        (user_id, start_date, end_date)
                    ).fetchall()
                    meetings = [dict(r) for r in rows]

                return {"tasks": tasks, "meetings": meetings}
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_query)

    async def get_all_records_for_search(self, user_id: int, record_type: str = "all") -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            records = []
            try:
                if record_type in ("all", "tasks"):
                    rows = conn.execute(
                        "SELECT id, title, due_date as date, due_time as time, 'task' as type FROM tasks WHERE user_id = ?",
                        (user_id,)
                    ).fetchall()
                    records.extend([dict(r) for r in rows])

                if record_type in ("all", "meetings"):
                    rows = conn.execute(
                        "SELECT id, title, start_date as date, start_time as time, 'meeting' as type, participants FROM meetings WHERE user_id = ?",
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
                    cur = conn.execute(
                        "UPDATE tasks SET status = 'completed' WHERE id = ? AND user_id = ?",
                        (task_id, user_id)
                    )
                    return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()
        return await asyncio.to_thread(_update)

    async def get_due_tasks(self, current_date: str, current_time: str) -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT t.id, t.user_id, t.title, t.due_date, t.due_time, t.is_reminder,
                           COALESCE(u.timezone, 'Europe/Moscow') as timezone
                    FROM tasks t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    WHERE t.status != 'completed'
                      AND t.reminder_sent = 0
                      AND t.due_date IS NOT NULL
                      AND t.due_time IS NOT NULL
                      AND (
                          (t.due_date = ? AND t.due_time <= ?)
                          OR (t.due_date < ?)
                      )
                    ORDER BY t.due_date ASC, t.due_time ASC
                    """,
                    (current_date, current_time, current_date)
                ).fetchall()
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

    async def get_due_meetings(self, current_date: str, current_time: str) -> List[Dict[str, Any]]:
        def _query():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT m.id, m.user_id, m.title, m.start_date, m.start_time, m.duration_minutes, m.participants,
                           COALESCE(u.timezone, 'Europe/Moscow') as timezone
                    FROM meetings m
                    LEFT JOIN users u ON m.user_id = u.user_id
                    WHERE m.reminder_sent = 0
                      AND m.start_date IS NOT NULL
                      AND m.start_time IS NOT NULL
                      AND (
                          (m.start_date = ? AND m.start_time <= ?)
                          OR (m.start_date < ?)
                      )
                    ORDER BY m.start_date ASC, m.start_time ASC
                    """,
                    (current_date, current_time, current_date)
                ).fetchall()
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
