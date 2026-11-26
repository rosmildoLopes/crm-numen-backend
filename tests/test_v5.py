from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
import json
from sqlalchemy import select,func,create_engine,text
from app.database import SessionLocal,Base
from app.models import Lead,CommercialTask,Outbox,Notification,ContactLog,AIUsage,Activity,CommercialRules,User,Course
from app.config import settings
from app import automation,ai
from test_v4 import client,role_headers,create_lead,age_lead
import pytest


def test_tasks_permissions_deadlines_and_dedup_notifications(client):
    lead=create_lead(client)
    h,seller=role_headers('vendedor')
    client.patch(f'/api/leads/{lead}',json={'assigned_to_id':seller})
    body={'lead_id':lead,'title':'Llamar','due_at':(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()}
    r=client.post('/api/tasks',json=body,headers=h)
    assert r.status_code==201,r.text
    id=r.json()['id']
    assert client.get('/api/tasks?state=overdue',headers=h).json()[0]['id']==id
    automation.run_once();automation.run_once()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.event_key==f'task_due:{id}'))==1
    assert client.patch(f'/api/tasks/{id}',json={'status':'done'},headers=h).status_code==200
    assert client.get('/api/tasks?state=overdue',headers=h).json()==[]
    assert client.patch(f'/api/tasks/{id}',json={'status':'pending'},headers=h).status_code==200
    h2,other=role_headers('supervisor_ventas')
    # A seller cannot delegate to another user or inspect someone else's lead.
    assert client.post('/api/tasks',headers=h,json={**body,'owner_id':other}).status_code==403
    assert client.post('/api/tasks',json={**body,'due_at':'2026-11-13T15:00:00'}).status_code==422
    unassigned=create_lead(client)
    assert client.post('/api/tasks',headers=h,json={**body,'lead_id':unassigned}).status_code==403


def test_tasks_follow_reassignment(client):
    lead=create_lead(client)
    _,first=role_headers('vendedor')
    client.patch(f'/api/leads/{lead}',json={'assigned_to_id':first})
    id=client.post('/api/tasks',json={'lead_id':lead,'title':'Próximo contacto','due_at':datetime.now(timezone.utc).isoformat()}).json()['id']
    with SessionLocal() as db:
        from app.security import hash_password
        second=User(email='second@example.com',full_name='Second',role='vendedor',password_hash=hash_password('password123'))
        db.add(second);db.commit();second_id=second.id
    client.patch(f'/api/leads/{lead}',json={'assigned_to_id':second_id})
    with SessionLocal() as db:assert db.get(CommercialTask,id).owner_id==second_id


def test_contact_reply_cancels_unsent_followup(client):
    lead=create_lead(client);age_lead(lead);automation.run_once()
    r=client.post(f'/api/leads/{lead}/contacts',json={'channel':'phone','outcome':'no_answer','detail':'Llamada sin respuesta'})
    assert r.status_code==201
    with SessionLocal() as db:assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')).status=='queued'
    assert client.post(f'/api/leads/{lead}/contacts',json={'channel':'email','outcome':'replied','detail':'Pidió temario'}).status_code==201
    assert client.get(f'/api/leads/{lead}').json()['status']=='contactado'
    with SessionLocal() as db:assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')).status=='cancelled'
    assert len(client.get(f'/api/leads/{lead}/contacts').json())==2


def test_manual_status_or_assignment_cancels_followup(client):
    lead=create_lead(client);age_lead(lead);automation.run_once()
    client.patch(f'/api/leads/{lead}',json={'status':'pensando'})
    with SessionLocal() as db:assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')).status=='cancelled'


def test_rules_threshold_no_email_and_automatic_assignment(client):
    _,seller=role_headers('vendedor')
    client.put('/api/commercial-rules',json={'followup_hours':2,'auto_assign':False,'followup_email':False})
    lead=create_lead(client);age_lead(lead,3)
    assert automation.run_once()['escalated']==1
    with SessionLocal() as db:assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')) is None
    client.put('/api/commercial-rules',json={'followup_hours':2,'auto_assign':True,'followup_email':False})
    assert automation.run_once()['assigned']==1
    assert client.get(f'/api/leads/{lead}').json()['assigned_to_id']==seller
    assert client.put('/api/commercial-rules',json={'followup_hours':0,'auto_assign':False,'followup_email':False}).status_code==422


def test_balanced_assignment_no_vendor_and_no_reassignment(client):
    assert client.post('/api/leads-auto-assign').json()['assigned']==0
    _,first=role_headers('vendedor')
    with SessionLocal() as db:
        from app.security import hash_password
        second=User(email='second@example.com',full_name='Second',role='vendedor',password_hash=hash_password('password123'))
        db.add(second);db.commit();second_id=second.id
    ids=[create_lead(client) for _ in range(5)]
    assert client.post('/api/leads-auto-assign').json()['assigned']==5
    assignments=[client.get(f'/api/leads/{id}').json()['assigned_to_id'] for id in ids]
    assert assignments.count(first)==3 and assignments.count(second_id)==2
    assert client.post('/api/leads-auto-assign').json()['assigned']==0


def test_csv_preview_duplicates_errors_and_idempotency(client):
    create_lead(client)
    csv='first_name,email,source,course_id\nDuplicada,ANA@example.com,web,\nNueva,nueva@example.com,web,\nRepetida,nueva@example.com,web,\nInválida,mal,web,\nCurso,curso@example.com,web,99999\n'
    data={'csv_text':csv,'commit':False}
    preview=client.post('/api/leads-import',json=data)
    assert preview.status_code==200,preview.text
    assert [r['status'] for r in preview.json()['rows']]==['duplicate','ready','duplicate','invalid','invalid']
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Lead))==1
    data['commit']=True
    assert client.post('/api/leads-import',json=data).json()['created']==1
    assert client.post('/api/leads-import',json=data).json()['created']==0
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(Outbox))==1 # imports do not enqueue emails
    assert client.post('/api/leads-import',json={'csv_text':'a,b\nx,y'}).status_code==422
    assert client.post('/api/leads-import',json={'csv_text':'first_name,email\n'+'A,a@example.com\n'*1001}).status_code==422
    h,_=role_headers('vendedor')
    assert client.post('/api/leads-import',json=data,headers=h).status_code==403


def test_duplicate_detection_does_not_merge_records(client):
    a=create_lead(client);b=create_lead(client)
    groups=client.get('/api/leads-duplicates').json()
    assert len(groups)==1
    assert {x['id'] for x in groups[0]['leads']}=={a,b}
    assert client.get(f'/api/leads/{b}').status_code==200


def test_metrics_money_permissions_and_currency(client):
    lead=create_lead(client)
    for name,currency,amount in [('A','ARS','10.25'),('B','USD','20.50')]:
        c=client.post('/api/courses',json={'name':name,'currency':currency}).json()['id']
        sale=client.post('/api/sales',json={'lead_id':lead,'course_id':c,'amount':amount,'payment_reference':name}).json()['id']
        client.post(f'/api/sales/{sale}/confirm',json={'reference':name})
    data=client.get('/api/commercial-metrics?dimension=source').json()
    row=data['items'][0]
    assert row['conversion']==100 and row['confirmed_sales']==2
    assert Decimal(row['revenue']['ARS'])==Decimal('10.25')
    assert Decimal(row['revenue']['USD'])==Decimal('20.50')
    h,_=role_headers('marketing')
    restricted=client.get('/api/commercial-metrics',headers=h).json()
    assert restricted['money_visible'] is False
    assert restricted['items'][0]['revenue']=={}
    seller,_=role_headers('vendedor')
    assert client.get('/api/commercial-metrics',headers=seller).json()['items']==[]


def test_ai_configuration_authorization_and_quota(client,monkeypatch):
    lead=create_lead(client)
    assert client.post(f'/api/leads/{lead}/ai-draft',json={'text':'hola','share_data':True}).status_code==503
    for k,v in {'ai_enabled':True,'openai_api_key':'test','openai_model':'test-model','ai_daily_call_limit':1}.items():monkeypatch.setattr(settings,k,v)
    monkeypatch.setattr(ai,'generate',lambda context:{'summary':'Consulta','suggested_reply':'Hola','next_action':'Llamar','needs_human':True})
    assert client.post(f'/api/leads/{lead}/ai-draft',json={'text':'hola'}).status_code==422
    body={'text':'hola','share_data':True}
    assert client.post(f'/api/leads/{lead}/ai-draft',json=body).status_code==200
    assert client.post(f'/api/leads/{lead}/ai-draft',json=body).status_code==429
    seller,_=role_headers('vendedor')
    assert client.post(f'/api/leads/{lead}/ai-draft',json=body,headers=seller).status_code==403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Outbox))==1 # no AI messages sent
        assert db.get(Lead,lead).status=='recibido'


def test_ai_response_contract_and_failure(monkeypatch):
    import httpx
    payloads=[]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'summary':'Resumen','suggested_reply':'Respuesta','next_action':'Contactar','needs_human':True})}]}]})
    original=httpx.Client
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    result=ai.generate({'consultation':'Texto de prueba'})
    assert result['summary']=='Resumen'
    assert payloads[0]['store'] is False and payloads[0]['text']['format']['strict'] is True
    assert 'tools' not in payloads[0]
    def bad(request):return httpx.Response(200,json={'status':'incomplete','output':[]})
    monkeypatch.setattr(ai.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(bad),**kw))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:ai.generate({})
    assert exc.value.status_code==502


def test_upgrade_v4_schema_preserves_rows(tmp_path):
    # Existing legacy tables plus the V4 notification records survive create_all.
    import sqlite3
    from pathlib import Path
    path=tmp_path/'v4.db';db=sqlite3.connect(path)
    db.executescript((Path(__file__).parent/'v3_schema.sql').read_text())
    db.executescript("CREATE TABLE notifications (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,lead_id INTEGER,event_key VARCHAR(120) NOT NULL,title VARCHAR(255) NOT NULL,message TEXT NOT NULL,read BOOLEAN NOT NULL,created_at DATETIME NOT NULL,UNIQUE(user_id,event_key)); INSERT INTO notifications VALUES(1,1,NULL,'old','V4','Mensaje',0,CURRENT_TIMESTAMP);")
    db.commit();db.close();engine=create_engine('sqlite:///'+str(path));Base.metadata.create_all(engine)
    with engine.connect() as db:assert db.execute(text('select title from notifications')).scalar()=='V4'
    engine.dispose()


def test_timezone_roundtrip_for_tasks_contacts_and_leads(client):
    lead=create_lead(client)
    assert client.get(f'/api/leads/{lead}').json()['created_at'].endswith('+00:00')
    r=client.post('/api/tasks',json={'lead_id':lead,'title':'Horario Buenos Aires','due_at':'2026-11-13T15:00:00-03:00'})
    assert r.status_code==201
    task=client.get('/api/tasks').json()[0]
    assert task['due_at']=='2026-11-13T18:00:00+00:00'
    client.post(f'/api/leads/{lead}/contacts',json={'channel':'phone','outcome':'no_answer','detail':'Prueba'})
    assert client.get(f'/api/leads/{lead}/contacts').json()[0]['created_at'].endswith('+00:00')
    assert client.get('/api/notifications').json()['items'][0]['created_at'].endswith('+00:00')
    assert client.get('/api/communications').json()[0]['created_at'].endswith('+00:00')



def test_legacy_local_admin_login(client):
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email=='admin@example.com'))
        user.email='admin@numen.local';db.commit()
    r=client.post('/api/auth/login',json={'email':'admin@numen.local','password':'test-password-123'})
    assert r.status_code==200 and r.json()['access_token']
