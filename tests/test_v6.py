from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit,parse_qs
import hashlib
import pytest
from sqlalchemy import select,func,create_engine,text,inspect
from test_v4 import client,role_headers,create_lead,age_lead
from app.database import SessionLocal,Base
from app.models import (Lead,Outbox,EmailSequence,SequenceStep,SequenceEnrollment,
    SequenceDispatch,EmailPreference,PreferenceHistory,UnsubscribeToken,
    CommercialTask,TaskReminderVersion,Notification,Sale,Course)
from app.config import settings
from app import automation,sequences

@pytest.fixture(autouse=True)
def local_url(monkeypatch):
    monkeypatch.setattr(settings,'public_crm_url','http://localhost:3000')


def grant(client,lead,consent='granted',blocked=False):
    r=client.put(f'/api/leads/{lead}/email-preferences',json={'consent':consent,'blocked':blocked,
        'source':'Formulario de prueba','evidence':'El interesado autorizó el seguimiento'})
    assert r.status_code==200,r.text
    return r.json()


def sequence(client,delays=(0,24),active=True):
    r=client.post('/api/sequences',json={'name':'Seguimiento V6','description':'Prueba',
        'steps':[{'delay_hours':d,'subject':'Hola {first_name}','body':'Tu consulta sobre {course_name}'} for d in delays]})
    assert r.status_code==201,r.text
    id=r.json()['id']
    if active:assert client.patch(f'/api/sequences/{id}/state',json={'state':'active'}).status_code==200
    return id


def enroll(client,lead,sequence):
    r=client.post(f'/api/leads/{lead}/sequence-enrollments',json={'sequence_id':sequence})
    assert r.status_code==201,r.text
    return r.json()['id']


def messages():
    with SessionLocal() as db:
        return [{'id':x.id,'status':x.status,'body':x.body,'lead_id':x.lead_id} for x in db.scalars(select(Outbox).where(Outbox.kind=='sequence_email')).all()]


def due(id,when):
    with SessionLocal() as db:db.get(SequenceEnrollment,id).next_due_at=when;db.commit()


def test_preferences_are_unknown_by_default_and_require_evidence(client):
    lead=create_lead(client)
    assert client.get(f'/api/leads/{lead}/email-preferences').json()['consent']=='unknown'
    assert client.put(f'/api/leads/{lead}/email-preferences',json={'consent':'granted','source':'web'}).status_code==422
    grant(client,lead)
    assert client.get(f'/api/leads/{lead}/email-preferences').json()['consent']=='granted'


def test_sequence_validation_preview_and_permissions(client):
    lead=create_lead(client);s=sequence(client,active=False)
    p=client.get(f'/api/sequences/{s}/preview?lead_id={lead}')
    assert p.status_code==200 and p.json()[0]['subject']=='Hola Ana'
    assert '[enlace de baja individual]' in p.json()[0]['body']
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(UnsubscribeToken))==0
    for steps in [[],[{'delay_hours':0,'subject':'Hola {bad}','body':'Texto'}],
        [{'delay_hours':0,'subject':'Hola\nBcc: x','body':'Texto'}],
        [{'delay_hours':0,'subject':'Hola','body':'Texto'},{'delay_hours':0,'subject':'Hola','body':'Texto'}]]:
        assert client.post('/api/sequences',json={'name':'Inválida','steps':steps}).status_code==422
    h,_=role_headers('vendedor')
    assert client.get('/api/sequences',headers=h).status_code==403
    assert client.post('/api/sequences',json={'name':'X','steps':[]},headers=h).status_code==403
    assert client.get('/api/sequence-enrollments',headers=h).status_code==403


def test_enrollment_requires_consent_and_prevents_duplicate_email(client):
    lead=create_lead(client);s=sequence(client)
    assert client.post(f'/api/leads/{lead}/sequence-enrollments',json={'sequence_id':s}).status_code==409
    grant(client,lead);e=enroll(client,lead,s)
    assert client.post(f'/api/leads/{lead}/sequence-enrollments',json={'sequence_id':s}).status_code==409
    duplicate=create_lead(client);other=sequence(client)
    assert client.post(f'/api/leads/{duplicate}/sequence-enrollments',json={'sequence_id':other}).status_code==409
    assert client.post(f'/api/sequence-enrollments/{e}/stop').status_code==200
    assert client.post(f'/api/leads/{lead}/sequence-enrollments',json={'sequence_id':s}).status_code==409 # no replay


def test_no_enrollment_for_contacted_closed_or_paid(client):
    s=sequence(client)
    for state in ['contactado','pensando','no_compro','compro']:
        lead=create_lead(client);grant(client,lead)
        with SessionLocal() as db:db.get(Lead,lead).status=state;db.commit()
        assert client.post(f'/api/leads/{lead}/sequence-enrollments',json={'sequence_id':s}).status_code==409


def test_queue_idempotency_and_delay_counts_from_actual_acceptance(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client);e=enroll(client,lead,s)
    now=datetime.now(timezone.utc)+timedelta(minutes=1)
    assert automation.run_once(now)['sequence_queued']==1
    assert automation.run_once(now)['sequence_queued']==0
    assert len(messages())==1
    assert messages()[0]['status']=='queued'
    # First step cannot advance while SMTP delivery remains disabled.
    assert automation.run_once(now+timedelta(days=3))['sequence_queued']==0
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    sent=[];monkeypatch.setattr(automation,'smtp_send',lambda item:sent.append(item.id))
    accepted=now+timedelta(days=4)
    automation.run_once(accepted)
    with SessionLocal() as db:
        item=db.get(SequenceEnrollment,e)
        assert item.next_position==2
        assert sequences.utc(item.next_due_at)==accepted+timedelta(hours=24)
    assert automation.run_once(accepted+timedelta(hours=23))['sequence_queued']==0
    assert automation.run_once(accepted+timedelta(hours=24))['sequence_queued']==1
    with SessionLocal() as db:assert db.get(SequenceEnrollment,e).state=='completed'
    assert len(messages())==2 and all(x['status']=='sent' for x in messages())


def test_pause_retains_queue_and_resume_sends_only_once(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client,delays=(0,));e=enroll(client,lead,s)
    automation.run_once()
    client.patch(f'/api/sequences/{s}/state',json={'state':'paused'})
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    sent=[];monkeypatch.setattr(automation,'smtp_send',lambda item:sent.append(item.kind))
    automation.run_once();assert messages()[0]['status']=='queued'
    assert 'sequence_email' not in sent
    client.patch(f'/api/sequences/{s}/state',json={'state':'active'})
    automation.run_once();automation.run_once()
    assert sent.count('sequence_email')==1


@pytest.mark.parametrize('action',['reply','status','email','purchase','manual','withdraw'])
def test_stop_conditions_cancel_queued_steps(client,action):
    lead=create_lead(client);grant(client,lead);s=sequence(client);e=enroll(client,lead,s);automation.run_once()
    if action=='reply':client.post(f'/api/leads/{lead}/contacts',json={'channel':'email','outcome':'replied','detail':'Respondió'})
    elif action=='status':client.patch(f'/api/leads/{lead}',json={'status':'contactado'})
    elif action=='email':client.patch(f'/api/leads/{lead}',json={'email':'cambio@example.com'})
    elif action=='manual':client.post(f'/api/sequence-enrollments/{e}/stop')
    elif action=='withdraw':grant(client,lead,'withdrawn')
    else:
        c=client.post('/api/courses',json={'name':'Curso'}).json()['id']
        sale=client.post('/api/sales',json={'lead_id':lead,'course_id':c,'amount':'10','payment_reference':'ref-v6'}).json()['id']
        assert client.post(f'/api/sales/{sale}/confirm',json={'reference':'ref-v6'}).status_code==200
    assert messages()[0]['status']=='cancelled'
    with SessionLocal() as db:assert db.get(SequenceEnrollment,e).state=='stopped'
    assert automation.run_once()['sequence_queued']==0


def test_no_answer_or_vendor_assignment_does_not_stop_sequence(client):
    lead=create_lead(client);grant(client,lead);s=sequence(client);e=enroll(client,lead,s)
    client.post(f'/api/leads/{lead}/contacts',json={'channel':'phone','outcome':'no_answer','detail':'No atendió'})
    _,seller=role_headers('vendedor');client.patch(f'/api/leads/{lead}',json={'assigned_to_id':seller})
    with SessionLocal() as db:assert db.get(SequenceEnrollment,e).state=='active'


def test_public_unsubscribe_is_an_explicit_post_and_shared_by_email(client):
    lead=create_lead(client);duplicate=create_lead(client);grant(client,lead);s=sequence(client);e=enroll(client,lead,s)
    automation.run_once();message=messages()[0]
    token=parse_qs(urlsplit(message['body'].splitlines()[-1]).query)['token'][0]
    with SessionLocal() as db:
        assert db.get(UnsubscribeToken,hashlib.sha256(token.encode()).hexdigest())
        assert not db.get(UnsubscribeToken,token)
    # No GET endpoint changes recipient state (protect against link scanners).
    assert client.get('/api/public/unsubscribe',params={'token':token}).status_code==405
    assert client.get(f'/api/leads/{lead}/email-preferences').json()['consent']=='granted'
    client.headers.pop('Authorization')
    assert client.post('/api/public/unsubscribe',json={'token':token}).status_code==200
    assert client.post('/api/public/unsubscribe',json={'token':token}).status_code==200
    with SessionLocal() as db:
        assert db.get(EmailPreference,'ana@example.com').blocked is True
        assert db.get(SequenceEnrollment,e).state=='stopped'
        assert db.scalar(select(func.count()).select_from(PreferenceHistory))==2 # grant and one unsubscribe
    assert messages()[0]['status']=='cancelled'


def test_invalid_and_expired_public_tokens(client):
    assert client.post('/api/public/unsubscribe',json={'token':'x'*43}).status_code==404
    assert client.post('/api/public/unsubscribe',json={'token':'bad'}).status_code==422
    token='T'*43
    with SessionLocal() as db:
        db.add(UnsubscribeToken(token_hash=hashlib.sha256(token.encode()).hexdigest(),email='expired@example.com',expires_at=datetime.now(timezone.utc)-timedelta(days=1)));db.commit()
    assert client.post('/api/public/unsubscribe',json={'token':token}).status_code==410


def test_blocking_shared_email_cancels_legacy_messages_without_cancelling_campus_event(client):
    lead=create_lead(client);age_lead(lead);automation.run_once()
    with SessionLocal() as db:
        db.add(Outbox(lead_id=lead,kind='campus_enrollment_pending',recipient='ana@example.com'));db.commit()
    grant(client,lead,blocked=True)
    duplicate=create_lead(client)
    p=client.get(f'/api/leads/{duplicate}/email-preferences').json()
    assert p['blocked'] is True
    with SessionLocal() as db:
        assert db.scalar(select(Outbox).where(Outbox.lead_id==duplicate,Outbox.kind=='welcome_lead')).status=='cancelled'
    with SessionLocal() as db:
        assert db.scalar(select(Outbox).where(Outbox.kind=='followup_12h')).status=='cancelled'
        assert db.scalar(select(Outbox).where(Outbox.kind=='campus_enrollment_pending')).status=='queued'


def test_preferences_are_checked_again_before_smtp(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client,delays=(0,));e=enroll(client,lead,s)
    automation.run_once()
    # Simulate an external preference change without calling its cancellation endpoint.
    with SessionLocal() as db:db.get(EmailPreference,'ana@example.com').consent='withdrawn';db.commit()
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    sent=[];monkeypatch.setattr(automation,'smtp_send',lambda x:sent.append(x.kind))
    automation.run_once()
    assert 'sequence_email' not in sent and messages()[0]['status']=='cancelled'


def test_smtp_uncertainty_holds_progress_then_manual_retry_works(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client,delays=(0,));e=enroll(client,lead,s)
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    def uncertain(item):
        if item.kind=='sequence_email':raise TimeoutError('simulated')
    monkeypatch.setattr(automation,'smtp_send',uncertain)
    automation.run_once()
    message=messages()[0];assert message['status']=='review'
    with SessionLocal() as db:assert db.get(SequenceEnrollment,e).next_position==1
    assert client.post(f"/api/communications/{message['id']}/retry").status_code==200
    monkeypatch.setattr(automation,'smtp_send',lambda item:None)
    automation.run_once()
    with SessionLocal() as db:assert db.get(SequenceEnrollment,e).state=='completed'


def test_content_immutable_after_enrollment_and_missing_url_blocks_activation(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client);enroll(client,lead,s)
    assert client.put(f'/api/sequences/{s}',json={'name':'Modificada','steps':[{'delay_hours':0,'subject':'Hola','body':'Texto'}]}).status_code==409
    monkeypatch.setattr(settings,'public_crm_url','')
    draft=sequence(client,active=False)
    assert client.patch(f'/api/sequences/{draft}/state',json={'state':'active'}).status_code==409
    assert client.get('/api/sequences').json()['public_url_configured'] is False


def test_sequence_enrollment_and_preferences_respect_seller_scope(client):
    lead=create_lead(client);grant(client,lead);s=sequence(client)
    h,seller=role_headers('vendedor')
    assert client.get(f'/api/leads/{lead}/email-preferences',headers=h).status_code==403
    assert client.post(f'/api/leads/{lead}/sequence-enrollments',headers=h,json={'sequence_id':s}).status_code==403
    client.patch(f'/api/leads/{lead}',json={'assigned_to_id':seller})
    assert client.post(f'/api/leads/{lead}/sequence-enrollments',headers=h,json={'sequence_id':s}).status_code==201
    assert client.get('/api/sequences-catalog',headers=h).status_code==200


def test_reschedule_timezone_permissions_and_new_due_reminder(client):
    lead=create_lead(client)
    past=datetime.now(timezone.utc)-timedelta(hours=2)
    task=client.post('/api/tasks',json={'lead_id':lead,'title':'Seguimiento','due_at':past.isoformat()}).json()['id']
    automation.run_once()
    r=client.post(f'/api/tasks/{task}/reschedule',json={'due_at':'2026-11-20T15:00:00-03:00'})
    assert r.status_code==200 and r.json()['due_at']=='2026-11-20T18:00:00+00:00'
    assert client.post(f'/api/tasks/{task}/reschedule',json={'due_at':'2026-11-20T15:00:00'}).status_code==422
    automation.run_once(datetime(2026,11,20,18,1,tzinfo=timezone.utc))
    automation.run_once(datetime(2026,11,20,18,2,tzinfo=timezone.utc))
    with SessionLocal() as db:
        keys=db.scalars(select(Notification.event_key).where(Notification.event_key.like(f'task_due:{task}%'))).all()
        assert set(keys)=={f'task_due:{task}',f'task_due:{task}:v1'}
    client.patch(f'/api/tasks/{task}',json={'status':'done'})
    assert client.post(f'/api/tasks/{task}/reschedule',json={'due_at':past.isoformat()}).status_code==409


def test_v5_schema_upgrade_preserves_data(tmp_path):
    import sqlite3
    from pathlib import Path
    # schema fixture is checked in without any production rows.
    path=tmp_path/'v5.db';db=sqlite3.connect(path)
    db.executescript((Path(__file__).parent/'v5_schema.sql').read_text())
    db.execute("INSERT INTO leads (id,first_name,last_name,email,phone,source,status,created_at,updated_at) VALUES (1,'Legacy V5','','legacy@example.com','','manual','recibido',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    db.commit();db.close()
    engine=create_engine('sqlite:///'+str(path));Base.metadata.create_all(engine)
    with engine.connect() as conn:assert conn.execute(text('select first_name from leads')).scalar()=='Legacy V5'
    assert 'sequence_enrollments' in inspect(engine).get_table_names()
    engine.dispose()



def test_legacy_email_does_not_restart_after_sequence_completes(client,monkeypatch):
    lead=create_lead(client);grant(client,lead);s=sequence(client,delays=(0,));e=enroll(client,lead,s)
    monkeypatch.setattr(settings,'email_delivery_enabled',True)
    monkeypatch.setattr(automation,'smtp_send',lambda item:None)
    automation.run_once()
    age_lead(lead,13);automation.run_once()
    with SessionLocal() as db:
        assert db.get(SequenceEnrollment,e).state=='completed'
        assert db.scalar(select(Outbox.id).where(Outbox.kind=='followup_12h')) is None


def test_reschedule_rejects_seller_outside_lead_scope(client):
    lead=create_lead(client)
    task=client.post('/api/tasks',json={'lead_id':lead,'title':'Seguimiento','due_at':datetime.now(timezone.utc).isoformat()}).json()['id']
    h,_=role_headers('vendedor')
    assert client.post(f'/api/tasks/{task}/reschedule',headers=h,json={'due_at':datetime.now(timezone.utc).isoformat()}).status_code==403
