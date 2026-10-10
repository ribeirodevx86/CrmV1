"""Pulso CRM Social Media: contatos, funil, propostas, planos e histórico.
Não contém funcionalidades nem integrações de envio de mensagens.
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.resolve()
DB_PATH = Path(os.environ.get('PULSO_DB', str(ROOT / 'data' / 'pulso.db')))
if not os.environ.get('DATABASE_URL'):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pulso')
UTC = timezone.utc
NOW = lambda: datetime.now(UTC).isoformat(timespec='seconds')
write_lock = __import__("threading").RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE, instagram_id TEXT UNIQUE, tags TEXT NOT NULL DEFAULT '',
 ig_last_inbound TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, category TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
"""
def db_open():
    if os.environ.get('DATABASE_URL'):
        from postgres_store import open_database
        return open_database(os.environ['DATABASE_URL'])
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

@contextmanager
def transaction():
    with write_lock:
        conn = db_open()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def initialize():
    if os.environ.get('DATABASE_URL'):
        from postgres_store import initialize_postgres
        initialize_postgres(os.environ['DATABASE_URL'])
        return
    with transaction() as con:
        con.executescript(SCHEMA)
        from crm_extension import ensure_crm_schema
        ensure_crm_schema(con)

def rowdict(row):
    return dict(row) if row is not None else None

def event(con, category, message):
    con.execute('INSERT INTO activity(category,message,created_at) VALUES (?,?,?)', (category, message[:400], NOW()))

def password_hash(pwd):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt, 350000)
    return salt.hex() + ':' + digest.hex()

def verify_password(pwd, stored):
    try:
        salt, digest = stored.split(':')
        guess = hashlib.pbkdf2_hmac('sha256', pwd.encode(), bytes.fromhex(salt), 350000)
        return hmac.compare_digest(guess, bytes.fromhex(digest))
    except Exception:
        return False

PHONE_PATTERN = re.compile(r'^\+[1-9]\d{7,14}$')
TEMPLATE_PATTERN = re.compile(r'^[a-z0-9_]{1,512}$')

def valid_phone(phone):
    if not phone: return None
    value = '+' + re.sub(r'\D', '', phone)
    if not PHONE_PATTERN.fullmatch(value):
        raise HTTPException(422, 'Informe telefone internacional válido, por exemplo +5511999999999.')
    return value

def request_session(request: Request, csrf=False):
    raw = request.cookies.get('pulso_session', '')
    if not raw: raise HTTPException(401, 'Faça login.')
    with transaction() as con:
        s = con.execute('SELECT sessions.*,users.email FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND expires_at>?',
                        (hashlib.sha256(raw.encode()).hexdigest(), NOW())).fetchone()
    if not s: raise HTTPException(401, 'Sessão expirada. Faça login.')
    if csrf and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), s['csrf']):
        raise HTTPException(403, 'Token de segurança inválido.')
    return dict(s)

def read_auth(request: Request): return request_session(request)
def write_auth(request: Request): return request_session(request, csrf=True)

app = FastAPI(title='Pulso Social CRM', version='3.0.0', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

@app.middleware('http')
async def security_headers(request, call_next):
    if request.method in ('POST','PUT','PATCH','DELETE') and request.url.path.startswith('/api/'):
        allowed=(os.environ.get('APP_ALLOWED_ORIGIN') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
        origin=request.headers.get('origin','').rstrip('/')
        if allowed and origin and origin != allowed:
            return JSONResponse({'detail':'Origem não autorizada'},status_code=403)
    resp=await call_next(request)
    resp.headers['X-Content-Type-Options']='nosniff'
    resp.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains' if os.environ.get('COOKIE_SECURE','false').lower()=='true' else 'max-age=0'
    resp.headers['X-Frame-Options']='DENY'
    resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    resp.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else 'no-cache'
    return resp


@app.on_event('startup')
def start():
    initialize()

@app.get('/')
def index(): return FileResponse(ROOT / 'static' / 'index.html')

class SetupIn(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=200)
    setup_key: str = ''

@app.get('/api/setup')
def setup_status():
    initialize()
    with transaction() as con:
        count = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    return {'required': count == 0}

@app.post('/api/setup')
def setup_account(data: SetupIn, request: Request):
    local_host = request.client and request.client.host in ('127.0.0.1','::1','testclient')
    configured = os.environ.get('APP_SETUP_KEY')
    if configured:
        if not hmac.compare_digest(data.setup_key, configured): raise HTTPException(403, 'Chave de instalação incorreta.')
    elif not local_host:
        raise HTTPException(403, 'Configure APP_SETUP_KEY antes de disponibilizar a instalação na rede.')
    email = data.email.strip().lower()
    if '@' not in email or len(email) > 254: raise HTTPException(422, 'E-mail inválido.')
    with transaction() as con:
        if con.execute('SELECT 1 FROM users LIMIT 1').fetchone(): raise HTTPException(409, 'Administrador já configurado.')
        con.execute('INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)', (email,password_hash(data.password),NOW()))
        event(con, 'security', 'Conta administradora inicial criada')
    return {'ok':True}

class Credentials(BaseModel):
    email: str
    password: str

@app.post('/api/login')
def login(data: Credentials):
    with transaction() as con:
        u = con.execute('SELECT * FROM users WHERE email=?', (data.email.strip().lower(),)).fetchone()
        if not u or not verify_password(data.password, u['password_hash']):
            raise HTTPException(401, 'E-mail ou senha incorretos.')
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        con.execute('DELETE FROM sessions WHERE expires_at<?', (NOW(),))
        con.execute('INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES(?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,(datetime.now(UTC)+timedelta(days=7)).isoformat(timespec='seconds')))
    r = JSONResponse({'ok':True,'csrf':csrf,'email':u['email']})
    r.set_cookie('pulso_session', token, httponly=True, samesite='lax', secure=os.environ.get('COOKIE_SECURE','false').lower()=='true', max_age=7*86400, path='/')
    return r

@app.post('/api/logout')
def logout(request:Request, session=Depends(write_auth)):
    with transaction() as con: con.execute('DELETE FROM sessions WHERE token_hash=?', (session['token_hash'],))
    r = JSONResponse({'ok':True});r.delete_cookie('pulso_session',path='/');return r

@app.get('/api/me')
def me(session=Depends(read_auth)):
    return {'email':session['email'], 'csrf':session['csrf']}


@app.get('/api/health')
def health():
    return {'ok': True, 'service': 'Pulso Social CRM', 'messaging': False}

@app.delete('/api/crm/contacts/{contact_id}')
def delete_crm_contact(contact_id:int,session=Depends(write_auth)):
    with transaction() as con:
        row=con.execute('SELECT id FROM contacts WHERE id=?',(contact_id,)).fetchone()
        if row is None: raise HTTPException(404,'Contato não encontrado.')
        count=con.execute('SELECT COUNT(*) FROM crm_deals WHERE contact_id=?',(contact_id,)).fetchone()[0]
        if count: raise HTTPException(409,'Este contato tem planos registrados. Exclua os planos primeiro para evitar perda acidental de histórico.')
        con.execute('DELETE FROM contacts WHERE id=?',(contact_id,))
        event(con,'crm',f'Contato excluído (ID {contact_id})')
    return {'ok':True}

from crm_extension import mount_crm
mount_crm(app,transaction,read_auth,write_auth,valid_phone,event,NOW)

if __name__=='__main__':
    import uvicorn
    uvicorn.run('app:app',host='127.0.0.1',port=8000,workers=1)
