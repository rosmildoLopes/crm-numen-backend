"""Additive V4 automation; SMTP delivery requires explicit configuration.

The database lease prevents concurrent runs. Ambiguous SMTP outcomes are held
for operator review rather than automatically duplicating an accepted message.
"""
from datetime import datetime, timedelta, timezone
from string import Formatter
import smtplib
from email.message import EmailMessage
from sqlalchemy import select, update
from .database import SessionLocal
from .models import (Lead, User, Course, Outbox, EmailTemplate, Notification,
                     AutomationEvent, WorkerLock, Delivery, Activity)
from .security import can
from .config import settings

DEFAULT_TEMPLATES={
 'welcome_lead': ('Recibimos tu consulta - Academia Numen',
 'Hola {first_name}, recibimos tu consulta sobre {course_name}. Pronto te contactaremos.\nEquipo Academia Numen'),
 'followup_12h': ('Seguimiento de tu consulta - Academia Numen',
 'Hola {first_name}, tu consulta sobre {course_name} sigue pendiente. Nuestro equipo se pondrá en contacto con vos.\nEquipo Academia Numen'),
}
ALLOWED={'first_name','last_name','course_name'}
def validate_template(subject, body):
    if '\r' in subject or '\n' in subject: raise ValueError('El asunto no admite saltos de línea')
    for text in (subject,body):
        for _,field,spec,conversion in Formatter().parse(text):
            if field is not None and (field not in ALLOWED or spec or conversion):
                raise ValueError('Variables permitidas: '+', '.join(sorted(ALLOWED)))

def initialize(db):
    for key,(subject,body) in DEFAULT_TEMPLATES.items():
        if not db.get(EmailTemplate,key): db.add(EmailTemplate(key=key,subject=subject,body=body))
    if not db.get(WorkerLock,'automation'):
        db.add(WorkerLock(key='automation',expires_at=datetime(2000,1,1,tzinfo=timezone.utc)))
    db.commit()

def render(db,key,lead):
    template=db.get(EmailTemplate,key)
    subject,body=(template.subject,template.body) if template else DEFAULT_TEMPLATES[key]
    course=db.get(Course,lead.course_id) if lead.course_id else None
    values=dict(first_name=lead.first_name,last_name=lead.last_name,course_name=course.name if course else 'nuestros cursos')
    return subject.format(**values),body.format(**values)

def enqueue(db,key,lead):
    from .sequences import blocked
    subject,body=render(db,key,lead)
    state='cancelled' if blocked(db,lead.email) else 'queued'
    db.add(Outbox(lead_id=lead.id,kind=key,recipient=lead.email,subject=subject,body=body,status=state))

def notify(db,user_id,key,title,message,lead_id=None):
    if not db.scalar(select(Notification.id).where(Notification.user_id==user_id,Notification.event_key==key)):
        db.add(Notification(user_id=user_id,event_key=key,title=title,message=message,lead_id=lead_id))

def smtp_send(item):
    if settings.demo_mode:raise ValueError("El modo demostración no permite enviar emails")
    if not settings.smtp_host or not settings.smtp_from:
        raise ValueError('Faltan SMTP_HOST o SMTP_FROM')
    message=EmailMessage()
    message['From']=settings.smtp_from;message['To']=item.recipient
    message['Subject']=item.subject
    message['Message-ID']=f'<numen-outbox-{item.id}@crm.numen.local>'
    message.set_content(item.body)
    with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=15) as smtp:
        smtp.ehlo()
        if settings.smtp_starttls: smtp.starttls();smtp.ehlo()
        if settings.smtp_user: smtp.login(settings.smtp_user,settings.smtp_password)
        smtp.send_message(message)

def run_once(now=None):
    now=now or datetime.now(timezone.utc)
    # Lease > maximum bounded SMTP batch duration (5 * 15 seconds plus TLS).
    with SessionLocal() as db:
        acquired=db.execute(update(WorkerLock).where(WorkerLock.key=='automation',WorkerLock.expires_at<=now)
            .values(expires_at=now+timedelta(minutes=10))).rowcount
        db.commit()
        if not acquired: return {'locked':True,'escalated':0,'sent':0}
    result={'locked':False,'escalated':0,'sent':0,'assigned':0,'sequence_queued':0}
    try:
        with SessionLocal() as db:
            # A crash after SMTP acceptance is ambiguous; require explicit review.
            for item in db.scalars(select(Outbox).where(Outbox.status=='sending')).all():
                item.status='review'
            from .commercial import rules, assign_waiting, notify_due_tasks
            rule=rules(db)
            notify_due_tasks(db,now)
            if rule.auto_assign:result['assigned']=assign_waiting(db)
            db.flush()
            from . import sequences
            result['sequence_queued']=sequences.process(db,now)
            db.flush()
            supervisors=[u for u in db.scalars(select(User).where(User.active.is_(True))).all() if can(u,'leads.assign')]
            leads=db.scalars(select(Lead).where(Lead.assigned_to_id.is_(None),
                Lead.created_at<=now-timedelta(hours=rule.followup_hours),Lead.status.in_(['recibido','pendiente_contacto']))).all()
            for lead in leads:
                key=f'followup_12h:{lead.id}'
                if db.get(AutomationEvent,key): continue
                db.add(AutomationEvent(key=key))
                if rule.followup_email and not sequences.has_sequence_history(db,lead.id) and not sequences.blocked(db,lead.email):
                    enqueue(db,'followup_12h',lead)
                db.add(Activity(lead_id=lead.id,action='followup_12h',detail=f'Escalado automático por {rule.followup_hours} horas sin asignación'))
                for user in supervisors:
                    notify(db,user.id,key,f'Consulta sin asignar hace {rule.followup_hours} horas',f'{lead.first_name} {lead.last_name}',lead.id)
                result['escalated']+=1
            db.commit()
            if settings.email_delivery_enabled:
                supported=list(DEFAULT_TEMPLATES)
                if sequences.valid_public_url():supported.append('sequence_email')
                items=db.scalars(select(Outbox).where(Outbox.status=='queued',
                    Outbox.kind.in_(supported)).order_by(Outbox.id)).all()
                attempts=0
                for item in items:
                    if attempts>=5:break
                    # Refresh after each SMTP transaction to respect recent stop requests.
                    db.expire_all();db.refresh(item)
                    if item.status!='queued':continue
                    decision=sequences.delivery_decision(db,item)
                    if decision=='hold':continue
                    if decision=='cancel':item.status='cancelled';db.commit();continue
                    if item.kind=='followup_12h':
                        lead=db.get(Lead,item.lead_id)
                        if not lead or lead.assigned_to_id is not None or lead.status not in {'recibido','pendiente_contacto'} or not rule.followup_email:
                            item.status='cancelled';db.commit();continue
                    delivery=db.get(Delivery,item.id)
                    if not delivery:
                        delivery=Delivery(outbox_id=item.id,attempts=0);db.add(delivery)
                    if delivery.attempts>=settings.email_max_attempts:
                        item.status='failed';db.commit();continue
                    item.status='sending';delivery.attempts+=1;attempts+=1;db.commit()
                    try:
                        smtp_send(item)
                    except (smtplib.SMTPRecipientsRefused,smtplib.SMTPAuthenticationError,ValueError):
                        item.status='failed';delivery.error='Configuración o destinatario rechazado. Revisar SMTP y destinatario.'
                    except Exception:
                        item.status='review';delivery.error='Entrega incierta; revisar proveedor antes de reintentar.'
                    else:
                        item.status='sent';delivery.error='';result['sent']+=1
                        sequences.on_sent(db,item,now)
                    db.commit()
            return result
    finally:
        with SessionLocal() as db:
            db.execute(update(WorkerLock).where(WorkerLock.key=='automation').values(expires_at=datetime(2000,1,1,tzinfo=timezone.utc)))
            db.commit()
