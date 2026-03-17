import sqlite3
from datetime import datetime

DB_NAME = 'bot_database.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    
    # Таблица заявок с полем app_type
    cur.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            answers TEXT,
            status TEXT,
            reviewer_id INTEGER,
            message_id INTEGER,
            ping_message_id INTEGER,
            claimed_by INTEGER,
            date TEXT,
            reviewed_at TEXT,
            app_type TEXT DEFAULT 'regular'
        )
    ''')
    
    # Таблица настроек
    cur.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('applications_open', 'true')")
    
    # Таблица портфелей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS portfolios (
            channel_id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            rank TEXT NOT NULL,
            tier INTEGER DEFAULT 0,
            pinned_by INTEGER,
            thread_rp_id INTEGER,
            thread_gang_id INTEGER,
            created_at TEXT
        )
    ''')
    
    # Таблица AFK
    cur.execute('''
        CREATE TABLE IF NOT EXISTS afk (
            user_id INTEGER PRIMARY KEY,
            start_time REAL NOT NULL,
            duration_seconds INTEGER NOT NULL,
            reason TEXT NOT NULL,
            channel_id INTEGER,
            notified_expired INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица отпусков (с полем roles)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS vacations (
            user_id INTEGER PRIMARY KEY,
            start_time REAL NOT NULL,
            duration_text TEXT NOT NULL,
            reason TEXT NOT NULL,
            channel_id INTEGER,
            roles TEXT
        )
    ''')
    
    # Таблица статистики игроков (для варнов и т.д.)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            user_id INTEGER PRIMARY KEY,
            accepted_by INTEGER,
            accepted_date TEXT,
            warns INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            voice_time INTEGER DEFAULT 0,
            last_updated TEXT
        )
    ''')
    
    # Таблица запросов повышения
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promotion_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT
        )
    ''')
    
    # Таблица запросов разбора отката
    cur.execute('''
        CREATE TABLE IF NOT EXISTS vod_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            vod_link TEXT,
            description TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT
        )
    ''')
    
    # Проверяем наличие поля roles в таблице vacations
    cur.execute("PRAGMA table_info(vacations)")
    columns = [col[1] for col in cur.fetchall()]
    if 'roles' not in columns:
        cur.execute("ALTER TABLE vacations ADD COLUMN roles TEXT")
    
    # Проверяем наличие поля app_type в таблице applications
    cur.execute("PRAGMA table_info(applications)")
    columns = [col[1] for col in cur.fetchall()]
    if 'app_type' not in columns:
        cur.execute("ALTER TABLE applications ADD COLUMN app_type TEXT DEFAULT 'regular'")
    
    conn.commit()
    conn.close()


# ---------- Заявки ----------
def add_application(user_id, answers_json, message_id, ping_message_id=None, app_type='regular'):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO applications (user_id, answers, status, message_id, ping_message_id, date, app_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, answers_json, 'pending', message_id, ping_message_id, datetime.now().isoformat(), app_type))
    app_id = cur.lastrowid
    conn.commit()
    conn.close()
    return app_id

def get_application(app_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, answers, status, reviewer_id, message_id, date, claimed_by, ping_message_id, reviewed_at, app_type FROM applications WHERE id = ?", (app_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_application_by_message(message_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, answers, status, reviewer_id, message_id, claimed_by, ping_message_id, reviewed_at, app_type FROM applications WHERE message_id = ?", (message_id,))
    row = cur.fetchone()
    conn.close()
    return row

def update_application_status(app_id, status, reviewer_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "UPDATE applications SET status = ?, reviewer_id = ?, reviewed_at = ? WHERE id = ?",
        (status, reviewer_id, datetime.now().isoformat(), app_id)
    )
    conn.commit()
    conn.close()

def set_application_claimed(app_id, claimed_by):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE applications SET claimed_by = ? WHERE id = ?", (claimed_by, app_id))
    conn.commit()
    conn.close()

def get_application_claimed(app_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT claimed_by FROM applications WHERE id = ?", (app_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_application_ping_message(app_id, ping_msg_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE applications SET ping_message_id = ? WHERE id = ?", (ping_msg_id, app_id))
    conn.commit()
    conn.close()

def get_user_applications(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, status, date, message_id FROM applications WHERE user_id = ? ORDER BY date DESC", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_all_applications(limit=50):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, status, date FROM applications ORDER BY date DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_last_rejected_time(user_id):
    """Возвращает дату последней отклонённой заявки пользователя или None."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT reviewed_at FROM applications 
        WHERE user_id = ? AND status = 'rejected' AND reviewed_at IS NOT NULL 
        ORDER BY reviewed_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0])
    return None

def clear_rejected_applications(user_id):
    """Удаляет все отклонённые заявки пользователя (снимает кулдаун)."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM applications WHERE user_id = ? AND status = 'rejected'", (user_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# ---------- Настройки ----------
def are_applications_open():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = 'applications_open'")
    row = cur.fetchone()
    conn.close()
    return row[0] == 'true'

def set_applications_open(value: bool):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE settings SET value = ? WHERE key = 'applications_open'", ('true' if value else 'false'))
    conn.commit()
    conn.close()


# ---------- Портфели ----------
def create_portfolio(channel_id, owner_id, rank, tier=0, pinned_by=None, thread_rp_id=None, thread_gang_id=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO portfolios (channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_portfolio_by_owner(owner_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT channel_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id FROM portfolios WHERE owner_id = ?", (owner_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_portfolio_by_channel(channel_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id FROM portfolios WHERE channel_id = ?", (channel_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_all_portfolios():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, created_at FROM portfolios")
    rows = cur.fetchall()
    conn.close()
    return rows

def update_portfolio_rank(channel_id, new_rank):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE portfolios SET rank = ? WHERE channel_id = ?", (new_rank, channel_id))
    conn.commit()
    conn.close()

def update_portfolio_tier(channel_id, new_tier):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE portfolios SET tier = ? WHERE channel_id = ?", (new_tier, channel_id))
    conn.commit()
    conn.close()

def update_portfolio_pinned(channel_id, pinned_by):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE portfolios SET pinned_by = ? WHERE channel_id = ?", (pinned_by, channel_id))
    conn.commit()
    conn.close()

def delete_portfolio(channel_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM portfolios WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()


# ---------- AFK ----------
def add_afk(user_id, start_time, duration_seconds, reason, channel_id=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO afk (user_id, start_time, duration_seconds, reason, channel_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, start_time, duration_seconds, reason, channel_id))
    conn.commit()
    conn.close()

def remove_afk(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM afk WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_afk(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT start_time, duration_seconds, reason FROM afk WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def is_afk(user_id):
    return get_afk(user_id) is not None

def get_all_afk():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, start_time, duration_seconds, reason FROM afk")
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_afk_notified(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE afk SET notified_expired = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_afk_to_notify():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM afk WHERE start_time + duration_seconds <= ? AND notified_expired = 0", (datetime.now().timestamp(),))
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]


# ---------- Отпуска ----------
def add_vacation(user_id, start_time, duration_text, reason, channel_id=None, roles=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO vacations (user_id, start_time, duration_text, reason, channel_id, roles)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, start_time, duration_text, reason, channel_id, roles))
    conn.commit()
    conn.close()

def remove_vacation(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM vacations WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_vacation(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT start_time, duration_text, reason, roles FROM vacations WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def is_on_vacation(user_id):
    return get_vacation(user_id) is not None

def get_all_vacations():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id, start_time, duration_text, reason FROM vacations")
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- Статистика игроков ----------
def create_or_update_player_stats(user_id, accepted_by=None, accepted_date=None, warns=None, points=None, voice_time=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
    exists = cur.fetchone()
    if exists:
        updates = []
        params = []
        if accepted_by is not None:
            updates.append("accepted_by = ?")
            params.append(accepted_by)
        if accepted_date is not None:
            updates.append("accepted_date = ?")
            params.append(accepted_date)
        if warns is not None:
            updates.append("warns = ?")
            params.append(warns)
        if points is not None:
            updates.append("points = ?")
            params.append(points)
        if voice_time is not None:
            updates.append("voice_time = ?")
            params.append(voice_time)
        updates.append("last_updated = ?")
        params.append(datetime.now().isoformat())
        params.append(user_id)
        cur.execute(f"UPDATE player_stats SET {', '.join(updates)} WHERE user_id = ?", params)
    else:
        cur.execute('''
            INSERT INTO player_stats (user_id, accepted_by, accepted_date, warns, points, voice_time, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, accepted_by, accepted_date, warns or 0, points or 0, voice_time or 0, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_player_stats(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT accepted_by, accepted_date, warns, points, voice_time FROM player_stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def add_warn(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE player_stats SET warns = warns + 1, last_updated = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    if cur.rowcount == 0:
        cur.execute('''
            INSERT INTO player_stats (user_id, warns, last_updated)
            VALUES (?, ?, ?)
        ''', (user_id, 1, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_warn(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT warns FROM player_stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row and row[0] > 0:
        cur.execute("UPDATE player_stats SET warns = warns - 1, last_updated = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def get_warns(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT warns FROM player_stats WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


# ---------- Запросы повышения ----------
def add_promotion_request(user_id, reason):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO promotion_requests (user_id, reason, requested_at)
        VALUES (?, ?, ?)
    ''', (user_id, reason, datetime.now().isoformat()))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id


# ---------- Запросы разбора отката ----------
def add_vod_request(user_id, vod_link, description):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO vod_requests (user_id, vod_link, description, requested_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, vod_link, description, datetime.now().isoformat()))
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id