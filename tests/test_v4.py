from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from sqlalchemy import select,create_engine,inspect
from app.main import app
from app.database import Base,engine,SessionLocal
from app.models import Lead,User,Outbox,Notification,Delivery,Activity
from app.security import hash_password,token_for
from app import automation
from app.config import settings
import pytest

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'email':'admin@example.com','password':'test-password-123'}).json()['access_token']
        c.headers['Authorization']='Bearer '+token
        yield c

def role_headers(role):
    with SessionLocal() as db:
        u=User(email=role+'@example.com',full_name=role,password_hash=hash_password('password123'),role=role)
        db.add(u);db.commit();return {'Authorization':'Bearer '+token_for(u)},u.id

def create_lead(client):
    r=client.post('/api/leads',json={'first_name':'Ana','email':'ana@example.com'})
    assert r.status_code==201,r.text
    return r.json()['id']

def age_lead(id,hours=13):
    with SessionLocal() as db:
        db.get(Lead,id).created_at=datetime.now(timezone.utc)-timedelta(hours=hours);db.commit()

def test_followup_threshold_and_idempotency(client):
    old=create_lead(client);age_lead(old)
    fresh=create_lead(client);age_lead(fresh,11.99)
    assert automation.run_once()['escalated']==1
    assert automation.run_once()['escalated']==0
    with SessionLocal() as db:
        assert len(db.scalars(select(Outbox).where(Outbox.kind=='followup_12h')).all())==1
        assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')).status=='queued'
    notices=client.get('/api/notifications').json()
    assert notices['unread']==1
    id=notices['items'][0]['id']
    assert client.post(f'/api/notifications/{id}/read').status_code==200
    assert client.get('/api/notifications').json()['unread']==0

def test_closed_and_assigned_excluded(client):
    for status in ['compro','no_compro']:
        id=create_lead(client);age_lead(id)
        with SessionLocal() as db:db.get(Lead,id).status=status;db.commit()
    h,seller=role_headers('vendedor')
    id=create_lead(client);age_lead(id)
    assert client.patch(f'/api/leads/{id}',json={'assigned_to_id':seller}).status_code==200
    assert automation.run_once()['escalated']==0
    assert client.get('/api/notifications',headers=h).json()['unread']==1

def test_access_isolation(client):
    id=create_lead(client);age_lead(id);automation.run_once()
    notice=client.get('/api/notifications').json()['items'][0]['id']
    h,_=role_headers('vendedor')
    for path in ['/api/communications','/api/email-templates','/api/leads-followup','/api/leads-export']:
        assert client.get(path,headers=h).status_code==403,path
    assert client.get(f'/api/leads/{id}',headers=h).status_code==403
    assert client.post(f'/api/notifications/{notice}/read',headers=h).status_code==404
    assert client.get('/api/notifications',headers=h).json()['items']==[]

def test_template_validation_rendering(client):
    assert client.put('/api/email-templates/welcome_lead',json={'subject':'Hola {first_name}','body':'Curso {course_name}'}).status_code==200
    id=create_lead(client)
    with SessionLocal() as db:
        message=db.scalar(select(Outbox).where(Outbox.lead_id==id))
        assert message.subject=='Hola Ana'
        assert message.body=='Curso nuestros cursos'
    for subject in ['Hola {first_name.__class__}','Hola {unknown}','Hola {first_name!r}','Hola\nBcc: x','Hola {']:
        assert client.put('/api/email-templates/welcome_lead',json={'subject':subject,'body':'Texto'}).status_code==422

def test_payment_and_existing_routes(client):
    lead=create_lead(client)
    c=client.post('/api/courses',json={'name':'Curso V4','price':'500'}).json()['id']
    sale=client.post('/api/sales',json={'lead_id':lead,'course_id':c,'amount':'500.25','payment_reference':'p-1'})
    assert sale.status_code==201
    id=sale.json()['id']
    body={'reference':'p-1'}
    h,_=role_headers('supervisor_ventas')
    assert client.post(f'/api/sales/{id}/confirm',json=body,headers=h).status_code==403
    assert client.post(f'/api/sales/{id}/confirm',json=body).status_code==200
    assert client.post(f'/api/sales/{id}/confirm',json=body).status_code==200
    assert client.get(f'/api/leads/{lead}').json()['status']=='compro'
    assert client.get('/api/sales-summary').json()['totals_by_currency']['ARS']['confirmed']==500.25
    with SessionLocal() as db:assert len(db.scalars(select(Outbox).where(Outbox.kind=='campus_enrollment_pending')).all())==1
    assert client.post(f'/api/leads/{lead}/notes',json={'text':'Seguimiento'}).status_code==201
    assert client.get(f'/api/leads/{lead}/activities').status_code==200
    assert client.patch(f'/api/leads/{lead}',json={'first_name':None}).status_code==422
    assert client.patch(f'/api/courses/{c}',json={'name':None}).status_code==422

def test_email_success_failure_and_manual_review(client,monkeypatch):
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    create_lead(client)
    sent=[]
    monkeypatch.setattr(automation,'smtp_send',lambda item:sent.append(item.id))
    assert automation.run_once()['sent']==1
    assert automation.run_once()['sent']==0
    assert len(sent)==1
    create_lead(client)
    def uncertain(item):raise TimeoutError('test')
    monkeypatch.setattr(automation,'smtp_send',uncertain)
    automation.run_once()
    rows=client.get('/api/communications').json()
    failed=next(x for x in rows if x['status']=='review')
    automation.run_once()
    assert client.get('/api/communications').json()[0]['attempts']==1
    assert client.post(f"/api/communications/{failed['id']}/retry").status_code==200
    monkeypatch.setattr(automation,'smtp_send',lambda item:None)
    assert automation.run_once()['sent']==1

def test_worker_lock_and_crash_recovery(client):
    from app.models import WorkerLock
    with SessionLocal() as db:
        db.get(WorkerLock,'automation').expires_at=datetime.now(timezone.utc)+timedelta(minutes=5);db.commit()
    assert automation.run_once()['locked'] is True
    with SessionLocal() as db:
        db.get(WorkerLock,'automation').expires_at=datetime(2000,1,1);db.commit()
    id=create_lead(client)
    with SessionLocal() as db:
        db.scalar(select(Outbox).where(Outbox.lead_id==id)).status='sending';db.commit()
    automation.run_once()
    assert client.get('/api/communications').json()[0]['status']=='review'

def test_csv_and_assignment_validation(client):
    lead=create_lead(client)
    client.patch(f'/api/leads/{lead}',json={'first_name':'=SUM(A1)'})
    r=client.get('/api/leads-export')
    assert r.status_code==200
    assert r.content.startswith(b'\xef\xbb\xbf')
    assert "'=SUM(A1)" in r.text
    h,_=role_headers('supervisor_ventas')
    assert client.get('/api/leads-export',headers=h).status_code==403
    assert client.patch(f'/api/leads/{lead}',json={'assigned_to_id':9999}).status_code==400

def test_additive_schema_preserves_v3(tmp_path):
    import sqlite3
    from pathlib import Path
    path=tmp_path/'v3.db'
    conn=sqlite3.connect(path)
    conn.executescript((Path(__file__).parent/'v3_schema.sql').read_text())
    conn.execute("INSERT INTO leads (id,first_name,last_name,email,phone,source,status,created_at,updated_at) VALUES (1,'Legacy','','legacy@example.com','','manual','recibido',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    conn.commit();conn.close()
    upgraded=create_engine('sqlite:///'+str(path))
    Base.metadata.create_all(upgraded)
    with upgraded.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text('select first_name from leads')).scalar()=='Legacy'
    assert 'notifications' in inspect(upgraded).get_table_names()
    upgraded.dispose()

def test_exact_twelve_hour_boundary(client):
    now=datetime.now(timezone.utc)
    id=create_lead(client)
    with SessionLocal() as db:
        db.get(Lead,id).created_at=now-timedelta(hours=12);db.commit()
    assert automation.run_once(now=now)['escalated']==1

def test_background_worker_starts(client,monkeypatch):
    import threading
    called=threading.Event()
    monkeypatch.setattr(settings,'automation_enabled',True)
    monkeypatch.setattr(automation,'run_once',lambda:called.set())
    with TestClient(app):
        assert called.wait(timeout=2),'Background worker did not start'

def test_smtp_protocol_and_message(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    class SMTP:
        def __init__(self,*a,**kw):calls.append(('connect',a,kw))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def ehlo(self):calls.append('ehlo')
        def starttls(self):calls.append('starttls')
        def login(self,u,p):calls.append(('login',u,p))
        def send_message(self,msg):calls.append(msg)
    monkeypatch.setattr(automation.smtplib,'SMTP',SMTP)
    for k,v in {'smtp_host':'smtp.example.com','smtp_from':'crm@example.com','smtp_user':'test','smtp_password':'secret','smtp_starttls':True}.items():
        monkeypatch.setattr(settings,k,v)
    automation.smtp_send(SimpleNamespace(id=42,recipient='ana@example.com',subject='Hola',body='Texto'))
    assert 'starttls' in calls
    assert ('login','test','secret') in calls
    assert calls[-1]['Message-ID']=='<numen-outbox-42@crm.numen.local>'
    assert calls[-1]['To']=='ana@example.com'
