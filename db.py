import sqlite3

def init_db(path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS donors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phrase TEXT UNIQUE
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    conn.commit()
    conn.close()

def add_donor(username, path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO donors(username) VALUES(?)", (username,))
    conn.commit()
    conn.close()

def get_donors(path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT username FROM donors")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_blacklist(phrase, path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO blacklist(phrase) VALUES(?)", (phrase,))
    conn.commit()
    conn.close()

def get_blacklist(path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT phrase FROM blacklist")
    rows = c.fetchall()
    conn.close()
    return [r[0].lower() for r in rows]

def set_config(key, value, path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    conn.commit()
    conn.close()

def get_config(key, path="data.db"):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
