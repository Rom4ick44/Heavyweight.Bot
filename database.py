import aiosqlite
from datetime import datetime

DB_NAME = 'bot_database.db'

async def init_db():
    """Инициализация базы данных, создание таблиц, если их нет."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица заявок
        await db.execute('''
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
                reviewed_at TEXT
            )
        ''')
        
        # Таблица настроек
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('applications_open', 'true')")
        
        # Таблица портфелей
        await db.execute('''
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
        await db.execute('''
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
        await db.execute('''
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
        await db.execute('''
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
        await db.execute('''
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
        await db.execute('''
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
        
        # Проверяем наличие поля roles в таблице vacations (если таблица уже существовала)
        cursor = await db.execute("PRAGMA table_info(vacations)")
        columns = [col[1] for col in await cursor.fetchall()]
        if 'roles' not in columns:
            await db.execute("ALTER TABLE vacations ADD COLUMN roles TEXT")
        
        await db.commit()


# ---------- Заявки ----------
async def add_application(user_id, answers_json, message_id, ping_message_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            INSERT INTO applications (user_id, answers, status, message_id, ping_message_id, date)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, answers_json, 'pending', message_id, ping_message_id, datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid

async def get_application(app_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT user_id, answers, status, reviewer_id, message_id, date, claimed_by, ping_message_id, reviewed_at FROM applications WHERE id = ?",
            (app_id,)
        )
        row = await cursor.fetchone()
        return row

async def get_application_by_message(message_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, user_id, answers, status, reviewer_id, message_id, claimed_by, ping_message_id, reviewed_at FROM applications WHERE message_id = ?",
            (message_id,)
        )
        row = await cursor.fetchone()
        return row

async def update_application_status(app_id, status, reviewer_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE applications SET status = ?, reviewer_id = ?, reviewed_at = ? WHERE id = ?",
            (status, reviewer_id, datetime.now().isoformat(), app_id)
        )
        await db.commit()

async def set_application_claimed(app_id, claimed_by):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE applications SET claimed_by = ? WHERE id = ?", (claimed_by, app_id))
        await db.commit()

async def get_application_claimed(app_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT claimed_by FROM applications WHERE id = ?", (app_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def set_application_ping_message(app_id, ping_msg_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE applications SET ping_message_id = ? WHERE id = ?", (ping_msg_id, app_id))
        await db.commit()

async def get_user_applications(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, status, date, message_id FROM applications WHERE user_id = ? ORDER BY date DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return rows

async def get_all_applications(limit=50):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, user_id, status, date FROM applications ORDER BY date DESC LIMIT ?",
            (limit,)
        )
        rows = await cursor.fetchall()
        return rows


# ---------- Настройки ----------
async def are_applications_open():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'applications_open'")
        row = await cursor.fetchone()
        return row[0] == 'true'

async def set_applications_open(value: bool):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET value = ? WHERE key = 'applications_open'", ('true' if value else 'false'))
        await db.commit()


# ---------- Портфели ----------
async def create_portfolio(channel_id, owner_id, rank, tier=0, pinned_by=None, thread_rp_id=None, thread_gang_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO portfolios (channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, datetime.now().isoformat()))
        await db.commit()

async def get_portfolio_by_owner(owner_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT channel_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id FROM portfolios WHERE owner_id = ?",
            (owner_id,)
        )
        row = await cursor.fetchone()
        return row

async def get_portfolio_by_channel(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id FROM portfolios WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return row

async def get_all_portfolios():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT channel_id, owner_id, rank, tier, pinned_by, thread_rp_id, thread_gang_id, created_at FROM portfolios")
        rows = await cursor.fetchall()
        return rows

async def update_portfolio_rank(channel_id, new_rank):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE portfolios SET rank = ? WHERE channel_id = ?", (new_rank, channel_id))
        await db.commit()

async def update_portfolio_tier(channel_id, new_tier):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE portfolios SET tier = ? WHERE channel_id = ?", (new_tier, channel_id))
        await db.commit()

async def update_portfolio_pinned(channel_id, pinned_by):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE portfolios SET pinned_by = ? WHERE channel_id = ?", (pinned_by, channel_id))
        await db.commit()

async def delete_portfolio(channel_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM portfolios WHERE channel_id = ?", (channel_id,))
        await db.commit()


# ---------- AFK ----------
async def add_afk(user_id, start_time, duration_seconds, reason, channel_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO afk (user_id, start_time, duration_seconds, reason, channel_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, start_time, duration_seconds, reason, channel_id))
        await db.commit()

async def remove_afk(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM afk WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_afk(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT start_time, duration_seconds, reason FROM afk WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row

async def is_afk(user_id):
    return await get_afk(user_id) is not None

async def get_all_afk():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, start_time, duration_seconds, reason FROM afk")
        rows = await cursor.fetchall()
        return rows

async def mark_afk_notified(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE afk SET notified_expired = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_afk_to_notify():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT user_id FROM afk WHERE start_time + duration_seconds <= ? AND notified_expired = 0",
            (datetime.now().timestamp(),)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# ---------- Отпуска ----------
async def add_vacation(user_id, start_time, duration_text, reason, channel_id=None, roles=None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO vacations (user_id, start_time, duration_text, reason, channel_id, roles)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, start_time, duration_text, reason, channel_id, roles))
        await db.commit()

async def remove_vacation(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM vacations WHERE user_id = ?", (user_id,))
        await db.commit()

async def get_vacation(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT start_time, duration_text, reason, roles FROM vacations WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row

async def is_on_vacation(user_id):
    return await get_vacation(user_id) is not None

async def get_all_vacations():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, start_time, duration_text, reason FROM vacations")
        rows = await cursor.fetchall()
        return rows


# ---------- Статистика игроков ----------
async def create_or_update_player_stats(user_id, accepted_by=None, accepted_date=None, warns=None, points=None, voice_time=None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM player_stats WHERE user_id = ?", (user_id,))
        exists = await cursor.fetchone()
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
            await db.execute(f"UPDATE player_stats SET {', '.join(updates)} WHERE user_id = ?", params)
        else:
            await db.execute('''
                INSERT INTO player_stats (user_id, accepted_by, accepted_date, warns, points, voice_time, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, accepted_by, accepted_date, warns or 0, points or 0, voice_time or 0, datetime.now().isoformat()))
        await db.commit()

async def get_player_stats(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT accepted_by, accepted_date, warns, points, voice_time FROM player_stats WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row

async def add_warn(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE player_stats SET warns = warns + 1, last_updated = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
        if db.total_changes == 0:
            await db.execute('''
                INSERT INTO player_stats (user_id, warns, last_updated)
                VALUES (?, ?, ?)
            ''', (user_id, 1, datetime.now().isoformat()))
        await db.commit()

async def remove_warn(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT warns FROM player_stats WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row and row[0] > 0:
            await db.execute("UPDATE player_stats SET warns = warns - 1, last_updated = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
            await db.commit()

async def get_warns(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT warns FROM player_stats WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


# ---------- Запросы повышения ----------
async def add_promotion_request(user_id, reason):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            INSERT INTO promotion_requests (user_id, reason, requested_at)
            VALUES (?, ?, ?)
        ''', (user_id, reason, datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid


# ---------- Запросы разбора отката ----------
async def add_vod_request(user_id, vod_link, description):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            INSERT INTO vod_requests (user_id, vod_link, description, requested_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, vod_link, description, datetime.now().isoformat()))
        await db.commit()
        return cursor.lastrowid