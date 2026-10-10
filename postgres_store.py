"""Minimal PostgreSQL compatibility for the existing SQLite-shaped CRM queries."""
import re
import psycopg
from psycopg.rows import dict_row

SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE, instagram_id TEXT UNIQUE, tags TEXT NOT NULL DEFAULT '', ig_last_inbound TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity(id BIGSERIAL PRIMARY KEY, category TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
'''
CRM_SCHEMA = '''
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS company TEXT NOT NULL DEFAULT '';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS pipeline_stage TEXT NOT NULL DEFAULT 'novo';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS proposal_status TEXT NOT NULL DEFAULT 'pendente';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS lead_source TEXT NOT NULL DEFAULT '';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS crm_description TEXT NOT NULL DEFAULT '';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS next_followup_at TEXT;
CREATE TABLE IF NOT EXISTS crm_deals(id BIGSERIAL PRIMARY KEY,contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,plan_name TEXT NOT NULL,monthly_cents BIGINT NOT NULL CHECK(monthly_cents>=0),status TEXT NOT NULL DEFAULT 'ativo' CHECK(status IN ('ativo','concluido','cancelado')),closed_date TEXT NOT NULL,remarks TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS crm_history(id BIGSERIAL PRIMARY KEY,contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,description TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_crm_deals_contact ON crm_deals(contact_id);
CREATE INDEX IF NOT EXISTS idx_crm_history_contact ON crm_history(contact_id);
'''
class Result:
    def __init__(self, cursor, lastrowid=None): self.cursor=cursor; self.lastrowid=lastrowid
    def fetchone(self):
        r=self.cursor.fetchone()
        return Row(r) if r is not None else None
    def fetchall(self): return [Row(r) for r in self.cursor.fetchall()]
    def __iter__(self): return (Row(r) for r in self.cursor)
class Row(dict):
    def __getitem__(self, key):
        if isinstance(key,int):return list(self.values())[key]
        return super().__getitem__(key)
class Connection:
    def __init__(self,url):self.db=psycopg.connect(url, row_factory=dict_row,connect_timeout=10)
    def execute(self,sql,params=()):
        sql=sql.replace('?', '%s')
        insert_id=bool(re.match(r'^\s*INSERT\s+INTO\s+(contacts|crm_deals|crm_history)\s*\(', sql, re.I))
        if insert_id:sql=sql.rstrip().rstrip(';')+' RETURNING id'
        # A failed INSERT during a CSV import should not poison the entire transaction.
        if re.match(r'^\s*INSERT\s+INTO\s+contacts\s*\(', sql, re.I):
            with self.db.transaction():
                cur=self.db.execute(sql,params)
                ident=cur.fetchone()['id'] if insert_id else None
                return Result(cur,ident)
        cur=self.db.execute(sql,params)
        ident=cur.fetchone()['id'] if insert_id else None
        return Result(cur,ident)
    def executescript(self,sql):
        for statement in sql.split(';'):
            if statement.strip(): self.db.execute(statement)
    def commit(self):self.db.commit()
    def rollback(self):self.db.rollback()
    def close(self):self.db.close()
def open_database(url):return Connection(url)
def initialize_postgres(url):
    conn=Connection(url)
    try:
        conn.executescript(SCHEMA)
        conn.executescript(CRM_SCHEMA)
        conn.commit()
    except Exception:
        conn.rollback();raise
    finally:conn.close()
