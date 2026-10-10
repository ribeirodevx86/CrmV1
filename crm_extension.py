"""CRM exclusivo: relacionamento, funil de vendas, planos fechados e acompanhamento."""
import sqlite3
try:
    from psycopg import IntegrityError as PostgresIntegrityError
except ImportError:
    PostgresIntegrityError = sqlite3.IntegrityError
DBIntegrityError=(sqlite3.IntegrityError, PostgresIntegrityError)
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

STAGES=('novo','contatado','reuniao','proposta','cliente','perdido')
ACCEPTANCE=('pendente','aceitou','recusou')
DEAL_STATUSES=('ativo','concluido','cancelado')

MIGRATION={
    'company':"TEXT NOT NULL DEFAULT ''",
    'email':"TEXT NOT NULL DEFAULT ''",
    'pipeline_stage':"TEXT NOT NULL DEFAULT 'novo'",
    'proposal_status':"TEXT NOT NULL DEFAULT 'pendente'",
    'lead_source':"TEXT NOT NULL DEFAULT ''",
    'crm_description':"TEXT NOT NULL DEFAULT ''",
    'next_followup_at':'TEXT'
}

def ensure_crm_schema(conn):
    existing={row['name'] for row in conn.execute('PRAGMA table_info(contacts)')}
    for key,definition in MIGRATION.items():
        if key not in existing:
            conn.execute(f'ALTER TABLE contacts ADD COLUMN {key} {definition}')
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS crm_deals(
          id INTEGER PRIMARY KEY,
          contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
          plan_name TEXT NOT NULL,
          monthly_cents INTEGER NOT NULL CHECK(monthly_cents>=0),
          status TEXT NOT NULL CHECK(status IN ('ativo','concluido','cancelado')) DEFAULT 'ativo',
          closed_date TEXT NOT NULL,
          remarks TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS crm_history(
          id INTEGER PRIMARY KEY,
          contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
          description TEXT NOT NULL,
          created_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_crm_deals_contact ON crm_deals(contact_id);
      CREATE INDEX IF NOT EXISTS idx_crm_history_contact ON crm_history(contact_id);
    ''')

class CRMContact(BaseModel):
    name: str=Field(min_length=2,max_length=140)
    phone:Optional[str]=None
    instagram_id:Optional[str]=Field(default=None,max_length=100)
    email:str=Field(default='',max_length=254)
    company:str=Field(default='',max_length=160)
    tags:str=Field(default='',max_length=150)
    pipeline_stage:str='novo'
    proposal_status:str='pendente'
    lead_source:str=Field(default='',max_length=160)
    crm_description:str=Field(default='',max_length=3000)
    next_followup_at:Optional[str]=None

class DealIn(BaseModel):
    plan_name:str=Field(min_length=2,max_length=160)
    monthly_value:str='0'
    status:str='ativo'
    closed_date:str=Field(default_factory=lambda:date.today().isoformat())
    remarks:str=Field(default='',max_length=1500)

class CRMImport(BaseModel):
    csv:str=Field(min_length=1,max_length=2000000)

class HistoryIn(BaseModel):
    description:str=Field(min_length=2,max_length=2000)

def date_or_none(value):
    if value in ('',None):return None
    try:return date.fromisoformat(value).isoformat()
    except (ValueError,TypeError):raise HTTPException(422,'Informe data válida no formato AAAA-MM-DD.')

def money_to_cents(value):
    try:
        v=Decimal(str(value).replace(',','.'))
        if not v.is_finite() or v<0 or v>100000000 or v.as_tuple().exponent < -2:
            raise ValueError()
        return int(v*100)
    except (InvalidOperation,ValueError):
        raise HTTPException(422,'Valor inválido. Use um número maior ou igual a zero, com até duas casas decimais.')

def prepare(d,valid_phone):
    if d.pipeline_stage not in STAGES or d.proposal_status not in ACCEPTANCE:
        raise HTTPException(422,'Etapa ou resposta à proposta inválida.')
    phone=valid_phone(d.phone)
    ig=(d.instagram_id or '').strip() or None
    email=d.email.strip().lower()
    if email and ('@' not in email or any(ch.isspace() for ch in email)):
        raise HTTPException(422,'E-mail inválido.')
    if not (email or ig or phone):raise HTTPException(422,'Informe pelo menos telefone, e-mail ou Instagram ID.')
    return (d.name.strip(),phone,ig,d.tags.strip(),email,d.company.strip(),d.pipeline_stage,
            d.proposal_status,d.lead_source.strip(),d.crm_description.strip(),date_or_none(d.next_followup_at))

def mount_crm(app, transaction, read_auth, write_auth, valid_phone, event, now):
    def exists(con,id):
        row=con.execute('SELECT * FROM contacts WHERE id=?',(id,)).fetchone()
        if row is None:raise HTTPException(404,'Contato não encontrado.')
        return row

    @app.get('/api/crm/summary')
    def summary(session=Depends(read_auth)):
        with transaction() as con:
            total=con.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
            proposals={r['proposal_status']:r['n'] for r in con.execute('SELECT proposal_status,COUNT(*) n FROM contacts GROUP BY proposal_status')}
            stages={r['pipeline_stage']:r['n'] for r in con.execute('SELECT pipeline_stage,COUNT(*) n FROM contacts GROUP BY pipeline_stage')}
            deals=con.execute("SELECT COUNT(*) total,COALESCE(SUM(CASE WHEN status='ativo' THEN monthly_cents ELSE 0 END),0) recurring_cents,COUNT(DISTINCT contact_id) buyers FROM crm_deals").fetchone()
            today=date.today().isoformat()
            due=con.execute("SELECT COUNT(*) FROM contacts WHERE next_followup_at IS NOT NULL AND next_followup_at<=? AND pipeline_stage NOT IN ('cliente','perdido')",(today,)).fetchone()[0]
            return {'total_contacts':total,'accepted':proposals.get('aceitou',0),'rejected':proposals.get('recusou',0),
                'pending':proposals.get('pendente',0),'deals_closed':deals['total'],'active_monthly_cents':deals['recurring_cents'],
                'customers_with_plans':deals['buyers'],'followups_due':due,
                'pipeline':[{ 'stage':st,'count':stages.get(st,0)} for st in STAGES]}


    @app.get('/api/crm/deals')
    def deals_list(session=Depends(read_auth)):
        with transaction() as con:
            rows=con.execute('''SELECT d.*, c.name contact_name,c.company company
                  FROM crm_deals d JOIN contacts c ON c.id=d.contact_id
                  ORDER BY d.closed_date DESC,d.id DESC LIMIT 3000''').fetchall()
        return {'items':[dict(r) for r in rows]}

    @app.get('/api/crm/contacts')
    def crm_contacts(search:str='',stage:str='',proposal:str='',session=Depends(read_auth)):
        if stage and stage not in STAGES:raise HTTPException(422,'Etapa inválida.')
        if proposal and proposal not in ACCEPTANCE:raise HTTPException(422,'Status inválido.')
        with transaction() as con:
            sql='''SELECT c.*,COUNT(d.id) closed_plans,
                COALESCE(SUM(CASE WHEN d.status='ativo' THEN d.monthly_cents ELSE 0 END),0) recurring_cents
                FROM contacts c LEFT JOIN crm_deals d ON d.contact_id=c.id
                WHERE (c.name LIKE ? OR c.company LIKE ? OR c.email LIKE ? OR COALESCE(c.phone,'') LIKE ?)
                AND (?='' OR c.pipeline_stage=?) AND (?='' OR c.proposal_status=?)
                GROUP BY c.id ORDER BY c.id DESC LIMIT 3000'''
            pat='%'+search[:150]+'%'
            rows=con.execute(sql,(pat,pat,pat,pat,stage,stage,proposal,proposal)).fetchall()
            return {'items':[dict(x) for x in rows]}

    @app.post('/api/crm/import')
    def crm_import(data:CRMImport,session=Depends(write_auth)):
        if len(data.csv.encode('utf-8'))>2000000:raise HTTPException(413,'CSV excede 2 MB.')
        try:dialect=csv.Sniffer().sniff(data.csv[:1024],delimiters=',;\t')
        except csv.Error:dialect=csv.excel
        reader=csv.DictReader(io.StringIO(data.csv.lstrip('\ufeff')),dialect=dialect)
        if not reader.fieldnames or 'nome' not in [x.lower().strip() for x in reader.fieldnames]:
            raise HTTPException(422,'CSV deve conter a coluna nome.')
        added=duplicates=invalid=0
        with transaction() as con:
            for i,row in enumerate(reader):
                if i>=1200:raise HTTPException(422,'Limite de 1.200 linhas por arquivo.')
                r={str(k).lower().strip():(v or '').strip() for k,v in row.items() if k is not None}
                try:
                    item=CRMContact(name=r.get('nome',''),phone=r.get('telefone') or None,
                        instagram_id=r.get('instagram_id') or None,email=r.get('email',''),
                        company=r.get('empresa',''),tags=r.get('etiquetas',''),
                        pipeline_stage=r.get('etapa','novo') or 'novo',
                        proposal_status=r.get('proposta','pendente') or 'pendente',
                        lead_source=r.get('origem',''),crm_description=r.get('observacoes',''),
                        next_followup_at=r.get('retorno') or None)
                    vals=prepare(item,valid_phone)
                except (ValueError,HTTPException,ValidationError):invalid+=1;continue
                if vals[4] and con.execute('SELECT 1 FROM contacts WHERE lower(email)=? LIMIT 1',(vals[4],)).fetchone():
                    duplicates+=1;continue
                try:
                    con.execute('INSERT INTO contacts(name,phone,instagram_id,tags,email,company,pipeline_stage,proposal_status,lead_source,crm_description,next_followup_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (*vals,now(),now()))
                    added+=1
                except DBIntegrityError:duplicates+=1
            event(con,'crm',f'Importação CRM: {added} novos contatos, {duplicates} duplicados')
        return {'added':added,'duplicates':duplicates,'invalid':invalid,'message':'Contatos importados para o CRM.'}

    @app.get('/api/crm/contacts/{contact_id}')
    def detail(contact_id:int,session=Depends(read_auth)):
        with transaction() as con:
            row=exists(con,contact_id)
            deals=[dict(r) for r in con.execute('SELECT * FROM crm_deals WHERE contact_id=? ORDER BY closed_date DESC,id DESC',(contact_id,))]
            history=[dict(r) for r in con.execute('SELECT * FROM crm_history WHERE contact_id=? ORDER BY id DESC',(contact_id,))]
            return {'contact':dict(row),'deals':deals,'history':history}

    @app.post('/api/crm/contacts')
    def create(data:CRMContact,session=Depends(write_auth)):
        vals=prepare(data,valid_phone)
        try:
            with transaction() as con:
                cur=con.execute('''INSERT INTO contacts(name,phone,instagram_id,tags,email,company,pipeline_stage,proposal_status,
                    lead_source,crm_description,next_followup_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (*vals,now(),now()))
                event(con,'crm','Lead comercial cadastrado: '+vals[0])
                return {'id':cur.lastrowid}
        except DBIntegrityError:raise HTTPException(409,'Telefone ou Instagram ID já cadastrado.')

    @app.put('/api/crm/contacts/{contact_id}')
    def update(contact_id:int,data:CRMContact,session=Depends(write_auth)):
        vals=prepare(data,valid_phone)
        try:
            with transaction() as con:
                exists(con,contact_id)
                con.execute('''UPDATE contacts SET name=?,phone=?,instagram_id=?,tags=?,email=?,company=?,
                     pipeline_stage=?,proposal_status=?,lead_source=?,crm_description=?,next_followup_at=?,updated_at=? WHERE id=?''',
                     (*vals,now(),contact_id))
                event(con,'crm','Lead comercial atualizado: '+vals[0])
            return {'ok':True}
        except DBIntegrityError:raise HTTPException(409,'Telefone ou Instagram ID já cadastrado.')

    @app.post('/api/crm/contacts/{contact_id}/deals')
    def add_deal(contact_id:int,data:DealIn,session=Depends(write_auth)):
        if data.status not in DEAL_STATUSES:raise HTTPException(422,'Status do plano inválido.')
        value=money_to_cents(data.monthly_value)
        closed=date_or_none(data.closed_date)
        if not closed:raise HTTPException(422,'Informe a data do fechamento.')
        with transaction() as con:
            exists(con,contact_id)
            cur=con.execute('''INSERT INTO crm_deals(contact_id,plan_name,monthly_cents,status,closed_date,remarks,created_at)
                 VALUES(?,?,?,?,?,?,?)''',(contact_id,data.plan_name.strip(),value,data.status,closed,data.remarks.strip(),now()))
            con.execute("UPDATE contacts SET pipeline_stage='cliente', proposal_status='aceitou', updated_at=? WHERE id=?",(now(),contact_id))
            event(con,'crm',f'Plano {data.plan_name.strip()} fechado para contato {contact_id}')
            return {'id':cur.lastrowid}

    @app.put('/api/crm/deals/{deal_id}')
    def update_deal(deal_id:int,data:DealIn,session=Depends(write_auth)):
        if data.status not in DEAL_STATUSES:raise HTTPException(422,'Status do plano inválido.')
        value=money_to_cents(data.monthly_value)
        closed=date_or_none(data.closed_date)
        if not closed:raise HTTPException(422,'Informe a data do fechamento.')
        with transaction() as con:
            r=con.execute('SELECT id FROM crm_deals WHERE id=?',(deal_id,)).fetchone()
            if not r:raise HTTPException(404,'Plano inexistente.')
            con.execute('UPDATE crm_deals SET plan_name=?,monthly_cents=?,status=?,closed_date=?,remarks=? WHERE id=?',
                 (data.plan_name.strip(),value,data.status,closed,data.remarks.strip(),deal_id))
            event(con,'crm','Plano atualizado: '+data.plan_name.strip())
        return {'ok':True}

    @app.delete('/api/crm/deals/{deal_id}')
    def remove_deal(deal_id:int,session=Depends(write_auth)):
        with transaction() as con:
            row=con.execute('SELECT plan_name FROM crm_deals WHERE id=?',(deal_id,)).fetchone()
            if not row:raise HTTPException(404,'Plano inexistente.')
            con.execute('DELETE FROM crm_deals WHERE id=?',(deal_id,))
            event(con,'crm','Registro de plano excluído: '+row['plan_name'])
        return {'ok':True}

    @app.post('/api/crm/contacts/{contact_id}/history')
    def add_history(contact_id:int,data:HistoryIn,session=Depends(write_auth)):
        with transaction() as con:
            exists(con,contact_id)
            cur=con.execute('INSERT INTO crm_history(contact_id,description,created_at) VALUES(?,?,?)',
                            (contact_id,data.description.strip(),now()))
            event(con,'crm',f'Interação anotada para contato {contact_id}')
            return {'id':cur.lastrowid}
