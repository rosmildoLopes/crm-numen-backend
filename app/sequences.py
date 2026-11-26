"""Sequence scheduling and recipient suppression. Called under the worker lease.

A step advances only after SMTP acceptance. Uncertain deliveries wait for review.
Messages already being handed to SMTP cannot be recalled by a concurrent opt-out.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from urllib.parse import urlsplit
from sqlalchemy import select, func
from .models import (EmailPreference, PreferenceHistory, EmailSequence, SequenceStep,
    SequenceEnrollment, SequenceDispatch, UnsubscribeToken, Lead, Course, Sale,
    Outbox, Activity)
from .config import settings
from .commercial import utc

EMAIL_KINDS={'welcome_lead','followup_12h','sequence_email'}
OPEN_STATUSES={'recibido','pendiente_contacto'}

def normalize(email):
    return email.strip().casefold()

def valid_public_url():
    try:
        parts=urlsplit(settings.public_crm_url)
        return bool(parts.scheme in {'http','https'} and parts.hostname and not parts.username
                    and not parts.password and not parts.query and not parts.fragment)
    except ValueError:
        return False

def preference(db,email):
    return db.get(EmailPreference,normalize(email))

def blocked(db,email):
    p=preference(db,email)
    return bool(p and p.blocked)

def permission_to_market(db,email):
    p=preference(db,email)
    return bool(p and not p.blocked and p.consent=='granted')

def apply_preference(db,email,consent,block,source,evidence,actor_id=None,lead_id=None):
    email=normalize(email)
    p=preference(db,email)
    if not p:
        p=EmailPreference(email=email);db.add(p)
    p.consent=consent;p.blocked=block;p.source=source;p.evidence=evidence;p.updated_by=actor_id
    p.updated_at=datetime.now(timezone.utc)
    db.add(PreferenceHistory(email=email,lead_id=lead_id,actor_id=actor_id,consent=consent,
        blocked=block,source=source,evidence=evidence))
    db.flush()
    if consent!='granted' or block:
        for item in db.scalars(select(SequenceEnrollment).where(
                SequenceEnrollment.recipient==email,SequenceEnrollment.state=='active')).all():
            stop(db,item,'Baja o cambio de preferencias')
    if block:
        for message in db.scalars(select(Outbox).where(
                func.lower(func.trim(Outbox.recipient))==email,
                Outbox.kind.in_(EMAIL_KINDS),Outbox.status.in_(['queued','failed','review']))).all():
            message.status='cancelled'
    return p

def stop(db,enrollment,reason,actor_id=None):
    if enrollment.state!='active':return
    enrollment.state='stopped';enrollment.reason=reason
    messages=db.scalars(select(Outbox).join(SequenceDispatch,SequenceDispatch.outbox_id==Outbox.id)
        .where(SequenceDispatch.enrollment_id==enrollment.id,Outbox.status.in_(['queued','failed','review']))).all()
    for item in messages:item.status='cancelled'
    db.add(Activity(lead_id=enrollment.lead_id,actor_id=actor_id,action='sequence_stopped',
        detail=f'Secuencia {enrollment.sequence_id}: {reason}'))

def stop_for_lead(db,lead_id,reason,actor_id=None):
    for item in db.scalars(select(SequenceEnrollment).where(
            SequenceEnrollment.lead_id==lead_id,SequenceEnrollment.state=='active')).all():
        stop(db,item,reason,actor_id)

def stop_reason(db,enrollment):
    lead=db.get(Lead,enrollment.lead_id)
    if not lead:return 'Lead inexistente'
    if normalize(lead.email)!=enrollment.recipient:return 'Cambió el email del lead'
    if not permission_to_market(db,enrollment.recipient):return 'Sin autorización de comunicación'
    if lead.status not in OPEN_STATUSES:return 'El interesado respondió o cerró la consulta'
    if db.scalar(select(Sale.id).where(Sale.lead_id==lead.id,Sale.status=='confirmed')):
        return 'Compra confirmada'
    return ''

def has_sequence_history(db,lead_id):
    # The legacy one-shot email must not restart after a sequence completes/stops.
    return bool(db.scalar(select(SequenceEnrollment.id).where(SequenceEnrollment.lead_id==lead_id)))

def steps_for(db,sequence_id):
    return db.scalars(select(SequenceStep).where(SequenceStep.sequence_id==sequence_id)
        .order_by(SequenceStep.position)).all()

def values_for(db,lead):
    course=db.get(Course,lead.course_id) if lead.course_id else None
    return {'first_name':lead.first_name,'last_name':lead.last_name,
            'course_name':course.name if course else 'nuestros cursos'}

def unsubscribe_link(db,email,now):
    token=secrets.token_urlsafe(32)
    db.add(UnsubscribeToken(token_hash=hashlib.sha256(token.encode()).hexdigest(),
        email=normalize(email),expires_at=now+timedelta(days=90)))
    return settings.public_crm_url.rstrip('/')+'/baja?token='+token

def process(db,now):
    queued=0
    # Validate stops even when the sequence is paused.
    items=db.scalars(select(SequenceEnrollment).where(SequenceEnrollment.state=='active')
        .order_by(SequenceEnrollment.next_due_at,SequenceEnrollment.id)).all()
    for enrollment in items:
        reason=stop_reason(db,enrollment)
        if reason:stop(db,enrollment,reason);continue
        sequence=db.get(EmailSequence,enrollment.sequence_id)
        if queued>=100:continue
        if sequence.state!='active' or utc(enrollment.next_due_at)>now or not valid_public_url():continue
        step=db.scalar(select(SequenceStep).where(SequenceStep.sequence_id==sequence.id,
            SequenceStep.position==enrollment.next_position))
        if not step:enrollment.state='completed';continue
        if db.scalar(select(SequenceDispatch.id).where(SequenceDispatch.enrollment_id==enrollment.id,
                SequenceDispatch.step_id==step.id)):continue
        lead=db.get(Lead,enrollment.lead_id)
        values=values_for(db,lead)
        link=unsubscribe_link(db,enrollment.recipient,now)
        message=Outbox(lead_id=lead.id,kind='sequence_email',recipient=enrollment.recipient,
            subject=step.subject.format(**values),
            body=step.body.format(**values)+'\n\nPara dejar de recibir emails: '+link)
        db.add(message);db.flush()
        db.add(SequenceDispatch(enrollment_id=enrollment.id,step_id=step.id,outbox_id=message.id))
        db.add(Activity(lead_id=lead.id,action='sequence_step_queued',
            detail=f'Secuencia {sequence.id}, paso {step.position}'))
        queued+=1
    return queued

def delivery_decision(db,item):
    if blocked(db,item.recipient):return 'cancel'
    if item.kind!='sequence_email':return 'send'
    dispatch=db.scalar(select(SequenceDispatch).where(SequenceDispatch.outbox_id==item.id))
    if not dispatch:return 'cancel'
    enrollment=db.get(SequenceEnrollment,dispatch.enrollment_id)
    if enrollment.state!='active':return 'cancel'
    reason=stop_reason(db,enrollment)
    if reason:stop(db,enrollment,reason);return 'cancel'
    if not valid_public_url():return 'hold'
    sequence=db.get(EmailSequence,enrollment.sequence_id)
    return 'send' if sequence and sequence.state=='active' else 'hold'

def on_sent(db,item,now):
    if item.kind!='sequence_email':return
    dispatch=db.scalar(select(SequenceDispatch).where(SequenceDispatch.outbox_id==item.id))
    if not dispatch:return
    dispatch.sent_at=now
    enrollment=db.get(SequenceEnrollment,dispatch.enrollment_id)
    if enrollment.state!='active':return
    following=db.scalar(select(SequenceStep).where(SequenceStep.sequence_id==enrollment.sequence_id,
        SequenceStep.position==enrollment.next_position+1))
    enrollment.next_position+=1
    if following:enrollment.next_due_at=now+timedelta(hours=following.delay_hours)
    else:enrollment.state='completed';enrollment.reason='Todos los pasos enviados'
