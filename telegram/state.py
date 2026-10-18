"""Durable, single-worker queue. Only opaque IDs are used as directory names."""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

class State:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'queue.sqlite3'
        with self.connect() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner INTEGER, chat INTEGER,
                mode TEXT, status TEXT, created REAL, error TEXT DEFAULT '', config TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, mode TEXT, settings TEXT DEFAULT '{}');
            ''')
            try:
                c.execute("ALTER TABLE users ADD COLUMN settings TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
            try:
                c.execute("ALTER TABLE jobs ADD COLUMN config TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass
    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()
    def recover(self):
        with self.connect() as c:
            c.execute("UPDATE jobs SET status='queued' WHERE status IN ('running','delivering')")
    def mode(self, uid, value=None):
        with self.connect() as c:
            if value:
                c.execute('INSERT INTO users(id, mode) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET mode=excluded.mode', (uid, value))
            row = c.execute('SELECT mode FROM users WHERE id=?', (uid,)).fetchone()
            return row['mode'] if row and row['mode'] else 'full'
    def get_settings(self, uid):
        with self.connect() as c:
            row = c.execute('SELECT settings, mode FROM users WHERE id=?', (uid,)).fetchone()
            if not row or not row['settings']:
                return {}
            try:
                return json.loads(row['settings'])
            except Exception:
                return {}
    def save_settings(self, uid, settings):
        with self.connect() as c:
            val = json.dumps(settings, ensure_ascii=False)
            mode = settings.get('mode', 'full')
            c.execute(
                'INSERT INTO users(id, mode, settings) VALUES(?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET settings=excluded.settings, mode=excluded.mode',
                (uid, mode, val)
            )
    def create(self, owner, chat, mode, suffix, data, config=None):
        if mode not in ('translate', 'audio', 'full') or suffix not in ('.txt', '.epub'):
            raise ValueError('Chế độ/định dạng không hợp lệ.')
        jid = uuid.uuid4().hex[:16]
        cfg_str = json.dumps(config or {}, ensure_ascii=False)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','delivering')").fetchone()[0] >= 10:
                raise ValueError('Hàng đợi đầy (10 truyện).')
            if c.execute("SELECT count(*) FROM jobs WHERE owner=? AND status IN ('queued','running','delivering')", (owner,)).fetchone()[0] >= 2:
                raise ValueError('Bạn đang có 2 truyện chờ/chạy. Hãy đợi hoặc hủy bớt.')
            folder = self.root / jid
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ('input' + suffix)).write_bytes(data)
            req_data = {'mode': mode, 'input': 'input' + suffix, 'config': config or {}}
            (folder / 'request.json').write_text(json.dumps(req_data, ensure_ascii=False), encoding='utf-8')
            c.execute('INSERT INTO jobs(id,owner,chat,mode,status,created,config) VALUES(?,?,?,?,?,?,?)',
                      (jid, owner, chat, mode, 'queued', time.time(), cfg_str))
        return jid
    def requeue(self, jid, owner):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM jobs WHERE id=? AND owner=?', (jid, owner)).fetchone()
            if not row or row['status'] not in ('failed','cancelled'):
                raise ValueError('Chỉ xếp hàng lại tác vụ lỗi/đã hủy.')
            c.execute("UPDATE jobs SET status='queued', error='' WHERE id=?", (jid,))
    def next(self):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created ASC LIMIT 1").fetchone()
            if not row: return None
            c.execute("UPDATE jobs SET status='running' WHERE id=?", (row['id'],))
            return dict(row)
    def set(self, jid, status, error=''):
        with self.connect() as c:
            c.execute('UPDATE jobs SET status=?, error=? WHERE id=?', (status, error, jid))
    def get(self, jid, owner=None):
        with self.connect() as c:
            q = 'SELECT * FROM jobs WHERE id=?'
            p = [jid]
            if owner:
                q += ' AND owner=?'
                p.append(owner)
            row = c.execute(q, p).fetchone()
            return dict(row) if row else None
    def list(self, owner):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM jobs WHERE owner=? AND status != "deleted" ORDER BY created DESC LIMIT 20', (owner,)).fetchall()]
