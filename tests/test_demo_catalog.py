from pathlib import Path
import json
from types import SimpleNamespace
from sqlalchemy import select,func
from fastapi import HTTPException
import pytest
from test_v4 import client
from app.database import SessionLocal
from app.models import Course,CourseCatalog,User,Lead,Sale,CommercialTask,DemoRecord
from app.demo_seed import populate
from app.config import settings,Settings
from app import automation,ai

CATALOG=Path(__file__).parent.parent/'data'/'catalogo-maestro-2027.json'

def test_demo_is_repeatable_and_preserves_admin(client,monkeypatch):
    monkeypatch.setattr(settings,'demo_mode',True)
    catalog=json.loads(CATALOG.read_text())
    with SessionLocal() as db:
        original=db.scalar(select(User).where(User.email=='admin@example.com'))
        original_id=original.id;original_hash=original.password_hash
        with db.begin_nested():first=populate(db,catalog,'TestDemoPass-2027!')
        db.commit()
    assert first['counts']['courses']==41
    assert first['counts']['leads']==36
    assert first['counts']['sales']==12
    assert first['counts']['commercial_tasks']==20
    assert first['counts']['users']==8
    with SessionLocal() as db:
        second=populate(db,catalog,'different-do-not-rotate');db.commit()
        original=db.get(User,original_id)
        assert original.password_hash==original_hash
        assert second['created']=={}
        assert second['counts']==first['counts']
        assert set(db.scalars(select(Lead.status)).all())=={'recibido','pendiente_contacto','contactado','pensando','no_compro','compro'}
        assert db.scalar(select(func.count()).select_from(Sale).where(Sale.status=='confirmed'))==6
        assert db.scalar(select(func.count()).select_from(CommercialTask).where(CommercialTask.status=='pending'))==10
    courses=client.get('/api/courses').json()
    assert len(courses)==41 and all(c['price_on_request'] and c['price'] is None for c in courses)
    assert len({c['school'] for c in courses})==8
    assert sum(c['program_type']=='Carrera' for c in courses)==24
    assert client.get('/api/dashboard').json()['total_leads']==36
    assert len(client.get('/api/leads-followup').json())==8
    assert client.get('/api/notifications').json()['unread']>0
    assert len(client.get('/api/sequence-enrollments').json())==4


def test_on_request_catalog_create_update_and_free_are_distinct(client):
    r=client.post('/api/courses',json={'name':'Consultar','price_on_request':True})
    assert r.status_code==201,r.text
    assert r.json()['price'] is None and r.json()['price_on_request'] is True
    id=r.json()['id']
    changed=client.patch(f'/api/courses/{id}',json={'price':'45000.00'})
    assert changed.status_code==200,changed.text
    assert changed.json()['price_on_request'] is False
    assert float(changed.json()['price'])==45000
    free=client.post('/api/courses',json={'name':'Gratuito explícito','price':'0','price_on_request':False})
    assert free.status_code==201 and free.json()['price'] is not None
    assert float(free.json()['price'])==0


def test_demo_mode_forces_external_actions_off(monkeypatch):
    value=Settings(_env_file=None,demo_mode=True,email_delivery_enabled=True,ai_enabled=True,automation_enabled=True)
    assert value.email_delivery_enabled is False and value.ai_enabled is False and value.automation_enabled is False
    monkeypatch.setattr(settings,'demo_mode',True)
    with pytest.raises(ValueError):automation.smtp_send(SimpleNamespace())
    with pytest.raises(HTTPException) as exc:ai.generate({})
    assert exc.value.status_code==503


def test_catalog_seed_cannot_run_without_demo_mode(client,monkeypatch):
    monkeypatch.setattr(settings,'demo_mode',False)
    with SessionLocal() as db:
        with pytest.raises(ValueError):populate(db,json.loads(CATALOG.read_text()),'TestDemoPass-2027!')
        assert db.scalar(select(func.count()).select_from(Lead))==0
