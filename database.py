"""SQLite storage and workflow operations for a dental laboratory."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator


DATABASE_PATH = Path(__file__).with_name("dental_lab.db")

STATUSES = {
    "assign_pending": "بانتظار التوزيع من المدير",
    "cad_pending": "بانتظار تصميم CAD",
    "cad_in_progress": "قيد تصميم CAD",
    "cam_pending": "بانتظار الخراطة CAM",
    "cam_in_progress": "قيد الخراطة CAM",
    "ceramic_pending": "بانتظار السيراميك",
    "ceramic_in_progress": "قيد أعمال السيراميك",
    "completed": "مكتمل",
}

STAGE_TRANSITIONS = {
    "cad": {
        "start": ("cad_pending", "cad_in_progress"),
        "complete": ("cad_in_progress", "cam_pending"),
    },
    "cam": {
        "start": ("cam_pending", "cam_in_progress"),
        "complete": ("cam_in_progress", "ceramic_pending"),
    },
    "ceramic": {
        "start": ("ceramic_pending", "ceramic_in_progress"),
        "complete": ("ceramic_in_progress", "completed"),
    },
}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the tables and seed default users if empty."""
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dental_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_number TEXT NOT NULL UNIQUE,
                patient_name TEXT NOT NULL,
                clinic_name TEXT NOT NULL,
                tooth_shade TEXT NOT NULL,
                priority TEXT NOT NULL,
                due_date TEXT NOT NULL,
                scanner_path TEXT NOT NULL,
                scanner_filename TEXT NOT NULL,
                design_path TEXT NOT NULL DEFAULT '',
                design_filename TEXT NOT NULL DEFAULT '',
                representative_notes TEXT NOT NULL DEFAULT '',
                assigned_designer_username TEXT NOT NULL DEFAULT '',
                assigned_designer_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN (
                    'assign_pending', 'cad_pending', 'cad_in_progress', 'cam_pending',
                    'cam_in_progress', 'ceramic_pending', 'ceramic_in_progress', 'completed'
                )),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS case_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES dental_cases(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                full_name TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_dental_cases_status ON dental_cases(status);
            CREATE INDEX IF NOT EXISTS idx_case_notes_case_id ON case_notes(case_id, created_at);
            """
        )
        
        # كود ترقية تلقائي لقاعدة البيانات لإضافة أعمدة التوزيع دون مسح بيانات الحالات القديمة
        try:
            connection.execute("ALTER TABLE dental_cases ADD COLUMN assigned_designer_username TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE dental_cases ADD COLUMN assigned_designer_name TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # بذر مستخدمين افتراضيين لكل قسم لتشغيل النظام فوراً
        default_users = [
            ('admin', 'admin123', 'dashboard', 'مدير المختبر'),
            ('rep1', 'delegate123', 'representative', 'المندوب أحمد'),
            ('cad1', 'cad123', 'cad', 'المصمم علي'),
            ('cad2', 'cad456', 'cad', 'المصممة نور'),
            ('cam1', 'cam123', 'cam', 'الفني مصطفى'),
            ('ceramic1', 'ceramist123', 'ceramic', 'الفني حسن')
        ]
        for username, password, role, full_name in default_users:
            try:
                connection.execute(
                    "INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
                    (username, password, role, full_name)
                )
            except sqlite3.IntegrityError:
                pass
def verify_user_login(username: str, password: str, role: str) -> dict[str, Any] | None:
    """Verify credentials against the user table and return user details if valid."""
    with _connection() as connection:
        row = connection.execute(
            "SELECT username, role, full_name FROM users WHERE username = ? AND password = ? AND role = ?",
            (username.strip(), password, role)
        ).fetchone()
    return dict(row) if row else None


def get_designers_list() -> list[dict[str, Any]]:
    """Return a list of all registered CAD designers in the system."""
    with _connection() as connection:
        rows = connection.execute(
            "SELECT username, full_name FROM users WHERE role = 'cad' ORDER BY full_name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def assign_case_to_designer(case_id: int, designer_username: str, designer_name: str, assigner_name: str) -> bool:
    """Assign a pending case to a specific designer and transition status to cad_pending."""
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE dental_cases 
            SET assigned_designer_username = ?, assigned_designer_name = ?, status = 'cad_pending', updated_at = CURRENT_TIMESTAMP 
            WHERE id = ? AND status = 'assign_pending'
            """,
            (designer_username, designer_name, case_id),
        )
        if cursor.rowcount != 1:
            return False
            
        connection.execute(
            """
            INSERT INTO case_notes (case_id, role, body)
            VALUES (?, ?, ?)
            """,
            (case_id, assigner_name, f"📥 تم توجيه وتعيين الحالة للمصمم: {designer_name}"),
        )
    return True


def create_case(
    *,
    patient_name: str,
    clinic_name: str,
    tooth_shade: str,
    priority: str,
    due_date: date | str,
    scanner_path: str,
    scanner_filename: str,
    representative_notes: str = "",
) -> int:
    """Create a case, initially queued for Manager Assignment, and return its database ID."""
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT INTO dental_cases (
                case_number, patient_name, clinic_name, tooth_shade, priority,
                due_date, scanner_path, scanner_filename, design_path, design_filename,
                representative_notes, assigned_designer_username, assigned_designer_name, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, '', '', 'assign_pending')
            """,
            (
                "pending",
                patient_name.strip(),
                clinic_name.strip(),
                tooth_shade,
                priority,
                due_date.isoformat() if isinstance(due_date, date) else due_date,
                scanner_path,
                scanner_filename,
                representative_notes.strip(),
            ),
        )
        case_id = int(cursor.lastrowid)
        case_number = f"DL-{date.today():%Y%m%d}-{case_id:06d}"
        connection.execute(
            "UPDATE dental_cases SET case_number = ? WHERE id = ?",
            (case_number, case_id),
        )
        if representative_notes.strip():
            connection.execute(
                """
                INSERT INTO case_notes (case_id, role, body)
                VALUES (?, ?, ?)
                """,
                (case_id, "المندوب", representative_notes.strip()),
            )
        return case_id


def get_cases(
    *,
    statuses: list[str] | tuple[str, ...] | None = None,
    search: str = "",
) -> list[dict[str, Any]]:
    """Return cases ordered by most recently updated."""
    query = "SELECT * FROM dental_cases WHERE 1 = 1"
    params: list[Any] = []

    if statuses is not None:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        query += f" AND status IN ({placeholders})"
        params.extend(statuses)

    if search.strip():
        pattern = f"%{search.strip()}%"
        query += """
            AND (
                case_number LIKE ? OR patient_name LIKE ? OR clinic_name LIKE ?
            )
        """
        params.extend((pattern, pattern, pattern))

    query += " ORDER BY updated_at DESC, id DESC"
    with _connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_case(case_id: int) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM dental_cases WHERE id = ?", (case_id,)
        ).fetchone()
    return dict(row) if row else None


def get_case_notes(case_id: int) -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT role, body, created_at
            FROM case_notes
            WHERE case_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (case_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_case_note(case_id: int, role: str, body: str) -> bool:
    note = body.strip()
    if not note or get_case(case_id) is None:
        return False

    with _connection() as connection:
        connection.execute(
            "INSERT INTO case_notes (case_id, role, body) VALUES (?, ?, ?)",
            (case_id, role, note),
        )
        connection.execute(
            "UPDATE dental_cases SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (case_id,),
        )
    return True


def save_case_design(case_id: int, design_path: str, design_filename: str) -> bool:
    """Save the CAD production file path and name to the case record."""
    if get_case(case_id) is None:
        return False
    with _connection() as connection:
        connection.execute(
            """
            UPDATE dental_cases 
            SET design_path = ?, design_filename = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
            """,
            (design_path, design_filename, case_id),
        )
    return True


def transition_case(
    case_id: int, stage: str, action: str, actor: str
) -> tuple[bool, str]:
    """Apply an allowed stage transition atomically and record it in the timeline."""
    if stage not in STAGE_TRANSITIONS or action not in STAGE_TRANSITIONS[stage]:
        return False, "الإجراء غير معروف."

    expected, target = STAGE_TRANSITIONS[stage][action]
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE dental_cases
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = ?
            """,
            (target, case_id, expected),
        )
        if cursor.rowcount != 1:
            return False, "تغيرت حالة الحالة أو لم تعد ضمن هذه المرحلة. حدّث الصفحة."

        connection.execute(
            """
            INSERT INTO case_notes (case_id, role, body)
            VALUES (?, ?, ?)
            """,
            (case_id, actor, f"تحولت الحالة إلى: {STATUSES[target]}"),
        )
    return True, STATUSES[target]
