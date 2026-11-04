"""Backward-compatible session store, durable work queue and atomic AI budget."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from lite_config import DB, now, stamp

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, number TEXT, name TEXT, started TEXT, updated TEXT,
 state TEXT, brief TEXT, refs TEXT, visuals TEXT, client_images TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session TEXT, at TEXT, dir TEXT, text TEXT, media TEXT);
CREATE TABLE IF NOT EXISTS ai_calls (at TEXT, session TEXT, kind TEXT, cost REAL);
CREATE TABLE IF NOT EXISTS budget_reservations (id TEXT PRIMARY KEY, at TEXT, session TEXT, kind TEXT, amount REAL, state TEXT);
CREATE TABLE IF NOT EXISTS reference_audit (id INTEGER PRIMARY KEY, at TEXT, session TEXT, call_id TEXT, path TEXT, sha256 TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, session TEXT, payload TEXT, state TEXT, created TEXT, updated TEXT, result TEXT, error TEXT, message_start INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS opportunities (session TEXT PRIMARY KEY, client TEXT, account_manager TEXT, date TEXT,
 value_estimate REAL, status TEXT DEFAULT 'open', converted_to_job INTEGER DEFAULT 0, job_no TEXT, design_hours REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS wa_inbound (id TEXT PRIMARY KEY, at TEXT, number TEXT, allowed INTEGER, payload TEXT);
CREATE TABLE IF NOT EXISTS wa_window (number TEXT PRIMARY KEY, last_inbound REAL);
CREATE TABLE IF NOT EXISTS wa_outbox (id TEXT PRIMARY KEY, number TEXT, payload TEXT, at TEXT, state TEXT, attempts INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session, at);
CREATE INDEX IF NOT EXISTS tasks_state ON tasks(state, created);
'''

@contextmanager
def connection():
    con = sqlite3.connect(str(DB), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def initialise():
    with connection() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript(SCHEMA)
        # A process interruption has an unknown provider outcome. Do not retry billable work.
        con.execute("UPDATE tasks SET state='error', error='Interrupted by a restart. Your brief is saved; review the latest images before retrying.', updated=? WHERE state='running'", (stamp(),))
        for row in con.execute('SELECT * FROM sessions').fetchall():
            sync_opportunity(decode(row), con)

def decode(row):
    if row is None:
        return None
    value = dict(row)
    for key in ('brief', 'refs', 'visuals', 'client_images'):
        value[key] = json.loads(value.get(key) or ('{}' if key == 'brief' else '[]'))
    return value

def load(sid):
    with connection() as con:
        return decode(con.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone())

def sync_opportunity(session, con):
    b = session['brief']
    con.execute('''INSERT INTO opportunities(session, client, account_manager, date) VALUES(?,?,?,?)
      ON CONFLICT(session) DO UPDATE SET client=excluded.client, account_manager=excluded.account_manager''',
      (session['id'], str(b.get('client', '')), str(b.get('account_manager', session.get('name', ''))), session['started'][:10]))

def save(session):
    session['updated'] = stamp()
    with connection() as con:
        con.execute('''UPDATE sessions SET name=?,updated=?,state=?,brief=?,refs=?,visuals=?,client_images=?,outcome=? WHERE id=?''',
          (session.get('name'),session['updated'],session['state'],json.dumps(session['brief']),json.dumps(session['refs']),
           json.dumps(session['visuals']),json.dumps(session['client_images']),session.get('outcome'),session['id']))
        sync_opportunity(session, con)

def message(sid, direction, text=None, media=None):
    with connection() as con:
        con.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', (uuid.uuid4().hex,sid,stamp(),direction,text,str(media) if media else None))

def setting(key, fallback):
    with connection() as con:
        row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else fallback

def set_setting(key, value):
    with connection() as con:
        con.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key,json.dumps(value)))

def spend(since=None):
    since = since or now().date().isoformat()
    with connection() as con:
        actual = con.execute('SELECT COALESCE(SUM(cost),0) FROM ai_calls WHERE at>=?', (since,)).fetchone()[0]
        pending = con.execute("SELECT COALESCE(SUM(amount),0) FROM budget_reservations WHERE at>=? AND state='reserved'", (since,)).fetchone()[0]
    return {'spent': round(actual, 6), 'reserved': round(pending, 6)}

class BudgetExceeded(Exception):
    pass

def reserve(sid, kind, amount):
    cap = float(setting('daily_cap', 3.0))
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        day = now().date().isoformat()
        used = con.execute('SELECT COALESCE(SUM(cost),0) FROM ai_calls WHERE at>=?', (day,)).fetchone()[0]
        pending = con.execute("SELECT COALESCE(SUM(amount),0) FROM budget_reservations WHERE at>=? AND state='reserved'", (day,)).fetchone()[0]
        if used + pending + amount > cap:
            raise BudgetExceeded("Today's AI budget is used up. Your brief is saved; you can continue tomorrow or ask the administrator to raise the cap.")
        rid = uuid.uuid4().hex
        con.execute('INSERT INTO budget_reservations VALUES(?,?,?,?,?,?)', (rid,stamp(),sid,kind,amount,'reserved'))
    return rid

def settle(rid, cost=None):
    with connection() as con:
        row = con.execute("SELECT * FROM budget_reservations WHERE id=? AND state='reserved'", (rid,)).fetchone()
        if not row:
            return
        amount = row['amount'] if cost is None else max(0, cost)
        con.execute('INSERT INTO ai_calls VALUES(?,?,?,?)', (stamp(),row['session'],row['kind'],amount))
        con.execute("UPDATE budget_reservations SET state='settled' WHERE id=?", (rid,))
