from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,field_validator,model_validator
from sqlalchemy import select,func,update,delete
from sqlalchemy.orm import Session
from .database import get_db
from .models import (User,Lead,Activity,EmailPreference,PreferenceHistory,EmailSequence,
    SequenceStep,SequenceEnrollment,SequenceDispatch,UnsubscribeToken,Outbox,
    CommercialTask,TaskReminderVersion,WorkerLock)
from .security import current_user,require,can
from .v5 import get_lead,edit_lead
from .commercial import utc,cancel_followups
from .automation import validate_template
from . import sequences

router=APIRouter(prefix='/api')

def acquire(db):
    now=datetime.now(timezone.utc)
    changed=db.execute(update(WorkerLock).where(WorkerLock.key=='automation',WorkerLock.expires_at<=now)
        .values(expires_at=now+timedelta(minutes=10))).rowcount
    if not changed:db.rollback();raise HTTPException(409,'Hay una operación en curso; intentá nuevamente')

def release(db):
    db.execute(update(WorkerLock).where(WorkerLock.key=='automation')
        .values(expires_at=datetime(2000,1,1,tzinfo=timezone.utc)))

class PreferenceInput(BaseModel):
    consent:Literal['unknown','granted','withdrawn']
    blocked:bool=False
    source:str=Field(min_length=1,max_length=120)
    evidence:str=Field(default='',max_length=3000)
    @model_validator(mode='after')
    def documented(self):
        self.source=self.source.strip();self.evidence=self.evidence.strip()
        if not self.source:raise ValueError('Indicar el origen del cambio')
        if self.consent=='granted' and not self.evidence:raise ValueError('Registrar cómo se obtuvo la autorización')
        return self

def preference_output(db,lead):
    p=sequences.preference(db,lead.email)
    return {'email':sequences.normalize(lead.email),'consent':p.consent if p else 'unknown',
        'blocked':p.blocked if p else False,'source':p.source if p else '',
        'evidence':p.evidence if p else '', 'updated_at':utc(p.updated_at) if p else None,
        'history':[{'id':h.id,'consent':h.consent,'blocked':h.blocked,'source':h.source,
                    'created_at':utc(h.created_at)} for h in db.scalars(select(PreferenceHistory)
            .where(PreferenceHistory.email==sequences.normalize(lead.email))
            .order_by(PreferenceHistory.id.desc()).limit(30)).all()]}

@router.get('/leads/{id}/email-preferences')
def get_preferences(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return preference_output(db,get_lead(db,id,user))

@router.put('/leads/{id}/email-preferences')
def put_preferences(id:int,body:PreferenceInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    lead=edit_lead(db,id,user)
    sequences.apply_preference(db,lead.email,body.consent,body.blocked,body.source,body.evidence,user.id,id)
    db.add(Activity(lead_id=id,actor_id=user.id,action='email_preferences_updated',
        detail=f'Autorización: {body.consent}; bloqueo: {body.blocked}; origen: {body.source}'))
    db.commit();return preference_output(db,lead)

class StepInput(BaseModel):
    delay_hours:int=Field(ge=0,le=720)
    subject:str=Field(min_length=1,max_length=255)
    body:str=Field(min_length=1,max_length=20000)
    @model_validator(mode='after')
    def check_template(self):
        if not self.subject.strip() or not self.body.strip():raise ValueError('Asunto y mensaje obligatorios')
        validate_template(self.subject,self.body)
        return self

class SequenceInput(BaseModel):
    name:str=Field(min_length=1,max_length=160)
    description:str=Field(default='',max_length=3000)
    steps:list[StepInput]=Field(min_length=1,max_length=8)
    @model_validator(mode='after')
    def check_steps(self):
        self.name=self.name.strip()
        if not self.name:raise ValueError('Nombre obligatorio')
        if any(step.delay_hours<1 for step in self.steps[1:]):
            raise ValueError('Entre pasos debe transcurrir al menos una hora')
        return self

class SequenceState(BaseModel):
    state:Literal['draft','active','paused']

def sequence_output(db,item):
    steps=sequences.steps_for(db,item.id)
    states=dict(db.execute(select(SequenceEnrollment.state,func.count()).where(
        SequenceEnrollment.sequence_id==item.id).group_by(SequenceEnrollment.state)).all())
    return {'id':item.id,'name':item.name,'description':item.description,'state':item.state,
        'enrollments':states,'editable':not bool(sum(states.values())),
        'steps':[{'position':s.position,'delay_hours':s.delay_hours,'subject':s.subject,'body':s.body} for s in steps]}

@router.get('/sequences')
def get_sequences(db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    from .config import settings
    return {'public_url_configured':sequences.valid_public_url(),'public_url':settings.public_crm_url,
        'items':[sequence_output(db,s) for s in db.scalars(select(EmailSequence).order_by(EmailSequence.id.desc())).all()]}

@router.post('/sequences',status_code=201)
def create_sequence(body:SequenceInput,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    item=EmailSequence(name=body.name,description=body.description,state='draft',created_by=user.id)
    db.add(item);db.flush()
    for position,step in enumerate(body.steps,1):db.add(SequenceStep(sequence_id=item.id,position=position,**step.model_dump()))
    db.commit();return sequence_output(db,item)

@router.put('/sequences/{id}')
def edit_sequence(id:int,body:SequenceInput,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    acquire(db)
    item=db.get(EmailSequence,id)
    if not item:raise HTTPException(404,'Secuencia inexistente')
    if db.scalar(select(SequenceEnrollment.id).where(SequenceEnrollment.sequence_id==id)):
        raise HTTPException(409,'Esta secuencia ya tiene inscripciones; creá una nueva versión')
    item.name=body.name;item.description=body.description
    db.execute(delete(SequenceStep).where(SequenceStep.sequence_id==id))
    for position,step in enumerate(body.steps,1):db.add(SequenceStep(sequence_id=id,position=position,**step.model_dump()))
    release(db);db.commit();return sequence_output(db,item)

@router.patch('/sequences/{id}/state')
def state_sequence(id:int,body:SequenceState,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    item=db.get(EmailSequence,id)
    if not item:raise HTTPException(404,'Secuencia inexistente')
    if body.state=='active' and not sequences.valid_public_url():
        raise HTTPException(409,'Configurar PUBLIC_CRM_URL para que funcione el enlace de baja')
    item.state=body.state;db.commit();return sequence_output(db,item)

@router.get('/sequences-catalog')
def sequence_catalog(db:Session=Depends(get_db),user:User=Depends(require('leads.read'))):
    return [{'id':s.id,'name':s.name,'step_count':len(sequences.steps_for(db,s.id))}
        for s in db.scalars(select(EmailSequence).where(EmailSequence.state=='active').order_by(EmailSequence.name)).all()]

@router.get('/sequences/{id}/preview')
def preview(id:int,lead_id:int,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    item=db.get(EmailSequence,id)
    if not item:raise HTTPException(404,'Secuencia inexistente')
    lead=get_lead(db,lead_id,user);values=sequences.values_for(db,lead)
    return [{'position':s.position,'delay_hours':s.delay_hours,'subject':s.subject.format(**values),
        'body':s.body.format(**values)+'\n\nPara dejar de recibir emails: [enlace de baja individual]'}
        for s in sequences.steps_for(db,id)]

class EnrollmentInput(BaseModel):
    sequence_id:int=Field(gt=0)

def enrollment_output(db,e):
    sequence=db.get(EmailSequence,e.sequence_id)
    lead=db.get(Lead,e.lead_id)
    messages=db.execute(select(SequenceStep.position,Outbox.status,Outbox.id)
        .join(SequenceDispatch,SequenceDispatch.step_id==SequenceStep.id)
        .join(Outbox,Outbox.id==SequenceDispatch.outbox_id)
        .where(SequenceDispatch.enrollment_id==e.id).order_by(SequenceStep.position)).all()
    return {'id':e.id,'lead_id':e.lead_id,'lead_name':f'{lead.first_name} {lead.last_name}',
        'sequence_id':e.sequence_id,'sequence_name':sequence.name,'sequence_state':sequence.state,
        'state':e.state,'next_position':e.next_position,'next_due_at':utc(e.next_due_at),
        'reason':e.reason,'messages':[{'position':p,'status':s,'outbox_id':i} for p,s,i in messages]}

@router.post('/leads/{id}/sequence-enrollments',status_code=201)
def enroll(id:int,body:EnrollmentInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    acquire(db)
    lead=edit_lead(db,id,user)
    sequence=db.get(EmailSequence,body.sequence_id)
    if not sequence or sequence.state!='active':raise HTTPException(409,'La secuencia no está activa')
    if not sequences.valid_public_url():raise HTTPException(409,'Falta configurar la URL para bajas')
    if not sequences.permission_to_market(db,lead.email):raise HTTPException(409,'Falta autorización de comunicación o hay un bloqueo')
    if lead.status not in sequences.OPEN_STATUSES:raise HTTPException(409,'El lead ya fue contactado o está cerrado')
    if db.scalar(select(SequenceEnrollment.id).where(SequenceEnrollment.sequence_id==sequence.id,SequenceEnrollment.lead_id==id)):
        raise HTTPException(409,'El lead ya participó en esta secuencia')
    email=sequences.normalize(lead.email)
    if db.scalar(select(SequenceEnrollment.id).where(SequenceEnrollment.recipient==email,SequenceEnrollment.state=='active')):
        raise HTTPException(409,'Este email ya tiene una secuencia en curso')
    step=sequences.steps_for(db,sequence.id)[0]
    enrollment=SequenceEnrollment(sequence_id=sequence.id,lead_id=id,recipient=email,created_by=user.id,
        state='active',next_position=1,next_due_at=datetime.now(timezone.utc)+timedelta(hours=step.delay_hours))
    if sequences.stop_reason(db,enrollment):raise HTTPException(409,'El lead no cumple las condiciones de seguimiento')
    db.add(enrollment);db.flush();cancel_followups(db,id)
    db.add(Activity(lead_id=id,actor_id=user.id,action='sequence_enrolled',detail=f'Secuencia {sequence.id}'))
    release(db);db.commit();return enrollment_output(db,enrollment)

@router.get('/leads/{id}/sequence-enrollments')
def lead_enrollments(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user)
    return [enrollment_output(db,e) for e in db.scalars(select(SequenceEnrollment)
        .where(SequenceEnrollment.lead_id==id).order_by(SequenceEnrollment.id.desc())).all()]

@router.get('/sequence-enrollments')
def all_enrollments(db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    return [enrollment_output(db,e) for e in db.scalars(select(SequenceEnrollment)
        .order_by(SequenceEnrollment.id.desc()).limit(500)).all()]

@router.post('/sequence-enrollments/{id}/stop')
def stop_enrollment(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    e=db.get(SequenceEnrollment,id)
    if not e:raise HTTPException(404,'Inscripción inexistente')
    edit_lead(db,e.lead_id,user)
    sequences.stop(db,e,'Detenida manualmente',user.id);db.commit();return {'ok':True}

class UnsubscribeInput(BaseModel):
    token:str=Field(min_length=20,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')

@router.post('/public/unsubscribe')
def unsubscribe(body:UnsubscribeInput,db:Session=Depends(get_db)):
    digest=hashlib.sha256(body.token.encode()).hexdigest()
    token=db.get(UnsubscribeToken,digest)
    if not token:raise HTTPException(404,'El enlace de baja no es válido')
    if utc(token.expires_at)<datetime.now(timezone.utc):raise HTTPException(410,'El enlace de baja venció. Solicitá la baja al equipo de Numen.')
    p=sequences.preference(db,token.email)
    if not p or p.consent!='withdrawn' or not p.blocked:
        sequences.apply_preference(db,token.email,'withdrawn',True,'Enlace de baja','Solicitud del destinatario')
    db.commit();return {'ok':True,'message':'Se registró la baja de emails para esta dirección.'}

class RescheduleInput(BaseModel):
    due_at:datetime
    @field_validator('due_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None:raise ValueError('La fecha debe incluir zona horaria')
        return value.astimezone(timezone.utc)

@router.post('/tasks/{id}/reschedule')
def reschedule(id:int,body:RescheduleInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    # Serialize reminder revision changes with the worker and other reschedules.
    acquire(db)
    task=db.get(CommercialTask,id)
    if not task:raise HTTPException(404,'Tarea inexistente')
    edit_lead(db,task.lead_id,user)
    if task.owner_id!=user.id and not can(user,'leads.assign'):raise HTTPException(403,'Sin permiso')
    if task.status!='pending':raise HTTPException(409,'Reabrí la tarea antes de reprogramar')
    version=db.get(TaskReminderVersion,id)
    if not version:version=TaskReminderVersion(task_id=id,revision=0);db.add(version)
    version.revision+=1;task.due_at=body.due_at
    db.add(Activity(lead_id=task.lead_id,actor_id=user.id,action='task_rescheduled',
        detail=f'Tarea {id}: {body.due_at.isoformat()}'))
    release(db);db.commit();return {'ok':True,'due_at':body.due_at}
