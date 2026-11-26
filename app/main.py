from contextlib import asynccontextmanager
import csv, io
import asyncio, logging
from . import automation
from .models import Notification, EmailTemplate, Delivery
from fastapi.responses import StreamingResponse
from datetime import datetime,timezone,timedelta
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import settings
from .database import Base,engine,get_db,SessionLocal
from .models import User,Course,Lead,LeadNote,Activity,Sale,Outbox
from .schemas import *
from .security import *

STATUSES={'recibido','pendiente_contacto','contactado','pensando','no_compro','compro'}
ROLES=set(ROLE_PERMISSIONS)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine) # MVP: en producción reemplazar con migraciones Alembic
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email==settings.admin_email)):
            db.add(User(email=settings.admin_email,full_name='Administrador',password_hash=hash_password(settings.admin_password),role='super_admin'))
            db.commit()
    with SessionLocal() as db:
        automation.initialize(db)
    async def poll():
        while True:
            try:
                await asyncio.to_thread(automation.run_once)
            except Exception:
                logging.exception('Error en automatización CRM')
            await asyncio.sleep(max(10, settings.automation_poll_seconds))
    task=asyncio.create_task(poll()) if settings.automation_enabled else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass

app=FastAPI(title='Academia Numen CRM API',version='6.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def reject_nulls(changes, nullable):
    if any(v is None and k not in nullable for k,v in changes.items()):
        raise HTTPException(422,'Este campo no admite null')

def audit(db,lead_id,actor_id,action,detail=''):
    db.add(Activity(lead_id=lead_id,actor_id=actor_id,action=action,detail=detail))
def lead_access(lead,user):
    if not can(user,'leads.read'):
        raise HTTPException(403,'Sin permiso')
    if user.role=='vendedor' and lead.assigned_to_id!=user.id: raise HTTPException(403,'Lead no asignado')

def get_lead(db,id,user):
    lead=db.get(Lead,id)
    if not lead: raise HTTPException(404,'Lead inexistente')
    lead_access(lead,user)
    return lead

@app.get('/health')
def health(): return {'status':'ok','demo_mode':settings.demo_mode}
@app.post('/api/auth/login',response_model=Token)
def login(body:Login,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email))
    if not user or not user.active or not verify_password(body.password,user.password_hash): raise HTTPException(401,'Credenciales inválidas')
    return Token(access_token=token_for(user))
@app.get('/api/auth/me',response_model=UserOut)
def me(user:User=Depends(current_user)): return user

@app.get('/api/users',response_model=list[UserOut])
def users(db:Session=Depends(get_db),user:User=Depends(require('users.manage'))): return db.scalars(select(User).order_by(User.id)).all()
@app.post('/api/users',response_model=UserOut,status_code=201)
def create_user(body:UserCreate,db:Session=Depends(get_db),user:User=Depends(require('users.manage'))):
    if body.role not in ROLES: raise HTTPException(400,'Rol inválido')
    if body.role=='super_admin' and user.role!='super_admin': raise HTTPException(403,'Rol reservado')
    if db.scalar(select(User).where(User.email==body.email)): raise HTTPException(409,'Email ya registrado')
    obj=User(email=body.email,full_name=body.full_name,password_hash=hash_password(body.password),role=body.role)
    db.add(obj);db.commit();db.refresh(obj);return obj
@app.patch('/api/users/{id}',response_model=UserOut)
def update_user(id:int,body:UserUpdate,db:Session=Depends(get_db),user:User=Depends(require('users.manage'))):
    obj=db.get(User,id)
    if not obj: raise HTTPException(404,'Usuario inexistente')
    if obj.role=='super_admin' and user.role!='super_admin': raise HTTPException(403,'No autorizado')
    changes=body.model_dump(exclude_unset=True)
    reject_nulls(changes, {'course_id','assigned_to_id','campus_course_id'})
    if 'role' in changes and changes['role'] not in ROLES: raise HTTPException(400,'Rol inválido')
    if changes.get('role')=='super_admin' and user.role!='super_admin': raise HTTPException(403,'Rol reservado')
    if obj.id==user.id and changes.get('active') is False: raise HTTPException(400,'No podés desactivar tu usuario')
    for k,v in changes.items():setattr(obj,k,v)
    db.commit();db.refresh(obj);return obj

@app.get('/api/courses',response_model=list[CourseOut])
def courses(db:Session=Depends(get_db),user:User=Depends(current_user)):return db.scalars(select(Course).order_by(Course.name)).all()
@app.post('/api/courses',response_model=CourseOut,status_code=201)
def create_course(body:CourseCreate,db:Session=Depends(get_db),user:User=Depends(require('courses.manage'))):
    if db.scalar(select(Course).where(Course.name==body.name)):raise HTTPException(409,'Curso duplicado')
    from .models import CourseCatalog
    obj=Course(**body.model_dump(exclude={'price_on_request'}));db.add(obj);db.flush()
    if body.price_on_request:db.add(CourseCatalog(course_id=obj.id,price_on_request=True))
    db.commit();db.refresh(obj);return obj

@app.get('/api/leads',response_model=list[LeadOut])
def leads(status:str|None=None,q:str|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can(user,'leads.read'):raise HTTPException(403,'Sin permiso')
    stmt=select(Lead).order_by(Lead.created_at.desc())
    if user.role=='vendedor':stmt=stmt.where(Lead.assigned_to_id==user.id)
    if status:stmt=stmt.where(Lead.status==status)
    if q:stmt=stmt.where((Lead.first_name.ilike(f'%{q}%'))|(Lead.last_name.ilike(f'%{q}%'))|(Lead.email.ilike(f'%{q}%')))
    return db.scalars(stmt.limit(500)).all()
@app.post('/api/leads',response_model=LeadOut,status_code=201)
def create_lead(body:LeadCreate,db:Session=Depends(get_db),user:User=Depends(require('leads.manage'))):
    if body.course_id and not db.get(Course,body.course_id):raise HTTPException(400,'Curso inválido')
    obj=Lead(**body.model_dump());db.add(obj);db.flush()
    audit(db,obj.id,user.id,'created','Lead creado manualmente')
    automation.enqueue(db,'welcome_lead',obj)
    db.commit();db.refresh(obj);return obj
@app.get('/api/leads/{id}',response_model=LeadOut)
def lead_detail(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):return get_lead(db,id,user)
@app.patch('/api/leads/{id}',response_model=LeadOut)
def update_lead(id:int,body:LeadUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    obj=get_lead(db,id,user);changes=body.model_dump(exclude_unset=True)
    reject_nulls(changes, {'course_id','assigned_to_id'})
    if not can(user,'leads.manage') and not can(user,'leads.own'):raise HTTPException(403,'Sin permiso para editar leads')
    if not can(user,'leads.manage') and any(k not in {'status','phone','first_name','last_name'} for k in changes):raise HTTPException(403,'No autorizado')
    if 'assigned_to_id' in changes and not can(user,'leads.assign'):raise HTTPException(403,'No puede asignar')
    if 'status' in changes and changes['status'] not in STATUSES:raise HTTPException(400,'Estado inválido')
    if 'status' in changes and changes['status']=='compro':raise HTTPException(400,'La compra se confirma desde pagos')
    if changes.get('course_id') and not db.get(Course,changes['course_id']):raise HTTPException(400,'Curso inválido')
    if changes.get('assigned_to_id'):
        target=db.get(User,changes['assigned_to_id'])
        if not target or not target.active or target.role!='vendedor':raise HTTPException(400,'Vendedor inválido')
    if 'assigned_to_id' in changes and changes['assigned_to_id'] and changes['assigned_to_id']!=obj.assigned_to_id:
        automation.notify(db,changes['assigned_to_id'],f'assigned:{id}:{datetime.now(timezone.utc).timestamp()}',
            'Nuevo lead asignado',f'{obj.first_name} {obj.last_name}',id)
    from .commercial import cancel_followups
    if changes.get('assigned_to_id') or changes.get('status') in {'contactado','pensando','compro','no_compro'}:
        cancel_followups(db,id)
    from .sequences import stop_for_lead
    if 'email' in changes and changes['email']!=obj.email:
        stop_for_lead(db,id,'Cambió el email del lead',user.id)
    if changes.get('status') in {'contactado','pensando','compro','no_compro'}:
        stop_for_lead(db,id,'Cambio de estado comercial',user.id)
    # Pending tasks follow a lead when its seller changes.
    if 'assigned_to_id' in changes and changes['assigned_to_id']:
        from .models import CommercialTask
        from sqlalchemy import update
        db.execute(update(CommercialTask).where(CommercialTask.lead_id==id,CommercialTask.status=='pending').values(owner_id=changes['assigned_to_id']))
    for k,v in changes.items():setattr(obj,k,v)
    audit(db,id,user.id,'updated',str(changes));db.commit();db.refresh(obj);return obj
@app.post('/api/leads/{id}/notes',response_model=NoteOut,status_code=201)
def add_note(id:int,body:NoteCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user)
    if not (can(user,'leads.manage') or can(user,'leads.own')):raise HTTPException(403,'Sin permiso para agregar notas')
    obj=LeadNote(lead_id=id,author_id=user.id,text=body.text);db.add(obj);audit(db,id,user.id,'note_added');db.commit();db.refresh(obj);return obj
@app.get('/api/leads/{id}/notes',response_model=list[NoteOut])
def notes(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user);return db.scalars(select(LeadNote).where(LeadNote.lead_id==id).order_by(LeadNote.created_at.desc())).all()
@app.get('/api/leads/{id}/activities',response_model=list[ActivityOut])
def activities(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user);return db.scalars(select(Activity).where(Activity.lead_id==id).order_by(Activity.created_at.desc())).all()

@app.get('/api/dashboard')
def dashboard(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can(user,'leads.read'):raise HTTPException(403,'Sin permiso')
    stmt=select(Lead)
    if user.role=='vendedor':stmt=stmt.where(Lead.assigned_to_id==user.id)
    items=db.scalars(stmt).all()
    from .commercial import rules
    hours=rules(db).followup_hours
    return {'followup_hours':hours,'total_leads':len(items),'unassigned':sum(x.assigned_to_id is None for x in items),'by_status':{s:sum(x.status==s for x in items) for s in sorted(STATUSES)},'overdue_unassigned':sum(x.assigned_to_id is None and x.status in {'recibido','pendiente_contacto'} and x.created_at.replace(tzinfo=timezone.utc)<=datetime.now(timezone.utc)-timedelta(hours=hours) for x in items)}

@app.post('/api/sales',response_model=SaleOut,status_code=201)
def create_sale(body:SaleCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    lead=get_lead(db,body.lead_id,user)
    if not (can(user,'sales.manage') or (can(user,'sales.own') and lead.assigned_to_id==user.id)):raise HTTPException(403,'Sin permiso')
    if not db.get(Course,body.course_id):raise HTTPException(400,'Curso inválido')
    if db.scalar(select(Sale).where(Sale.payment_reference==body.payment_reference)):raise HTTPException(409,'Referencia duplicada')
    obj=Sale(**body.model_dump(),status='pending');db.add(obj);db.commit();db.refresh(obj);return obj
@app.get('/api/sales',response_model=list[SaleOut])
def sales(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not (can(user,'sales.manage') or can(user,'sales.read') or can(user,'sales.own')):raise HTTPException(403,'Sin permiso')
    stmt=select(Sale)
    if user.role=='vendedor':stmt=stmt.join(Lead).where(Lead.assigned_to_id==user.id)
    return db.scalars(stmt.order_by(Sale.id.desc())).all()
@app.post('/api/sales/{id}/confirm',response_model=SaleOut)
def confirm_sale(id:int,body:PaymentConfirm,db:Session=Depends(get_db),user:User=Depends(require('sales.manage'))):
    sale=db.get(Sale,id)
    if not sale:raise HTTPException(404,'Venta inexistente')
    if sale.payment_reference!=body.reference:raise HTTPException(400,'Referencia no coincide')
    if sale.status=='confirmed':return sale
    # MVP: confirmación MANUAL; no representa verificación contra proveedor de pagos.
    sale.status='confirmed';lead=db.get(Lead,sale.lead_id);lead.status='compro'
    from .commercial import cancel_followups
    cancel_followups(db,lead.id)
    from .sequences import stop_for_lead
    stop_for_lead(db,lead.id,'Compra confirmada',user.id)
    audit(db,lead.id,user.id,'payment_manually_confirmed',f'Venta {sale.id}')
    db.add(Outbox(lead_id=lead.id,kind='campus_enrollment_pending',recipient=lead.email,subject='Matrícula pendiente de integración',body=f'Venta {sale.id} confirmada manualmente. Integrar Campus antes de habilitar accesos.'))
    db.commit();db.refresh(sale);return sale
@app.get('/api/outbox')
def outbox(db:Session=Depends(get_db),user:User=Depends(require('dashboard.all'))):
    return [{'id':x.id,'kind':x.kind,'recipient':x.recipient,'status':x.status,'subject':x.subject} for x in db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(100)).all()]


@app.get('/api/leads-followup')
def leads_followup(db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Cola de supervisión: leads sin asignar y antigüedad >= 12 horas.

    Es una consulta en tiempo real; NO envía mensajes ni ejecuta trabajos programados.
    """
    if not can(user,'leads.assign'):raise HTTPException(403,'Sin permiso para ver cola de asignación')
    from .commercial import rules
    hours=rules(db).followup_hours
    cutoff=datetime.now(timezone.utc)-timedelta(hours=hours)
    pending=db.scalars(select(Lead).where(Lead.assigned_to_id.is_(None),Lead.status.notin_(['compro','no_compro'])).order_by(Lead.created_at.asc())).all()
    def utc(value):return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return [{'id':lead.id,'name':f'{lead.first_name} {lead.last_name}'.strip(),
             'email':lead.email,'course_id':lead.course_id,'created_at':utc(lead.created_at),
             'hours_waiting':round((datetime.now(timezone.utc)-utc(lead.created_at)).total_seconds()/3600,1),
             'overdue':utc(lead.created_at)<=cutoff} for lead in pending]


# V3: Exportación controlada; el rol supervisor NO dispone de leads.export.
@app.get('/api/leads-export')
def export_leads(db:Session=Depends(get_db),user:User=Depends(require('leads.export'))):
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(['id','nombre','apellido','email','telefono','origen','estado','curso_id','vendedor_id','creado'])
    for x in db.scalars(select(Lead).order_by(Lead.id)).all():
        # Evita interpretación como fórmulas al abrir CSV en hojas de cálculo.
        def safe(v):
            v=str(v if v is not None else '')
            return "'"+v if v.lstrip().startswith(('=','+','-','@')) else v
        writer.writerow([safe(v) for v in [x.id,x.first_name,x.last_name,x.email,x.phone,x.source,x.status,x.course_id,x.assigned_to_id,x.created_at]])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue().encode('utf-8-sig')]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="numen-leads.csv"'})

@app.patch('/api/courses/{id}',response_model=CourseOut)
def update_course(id:int,body:CourseUpdate,db:Session=Depends(get_db),user:User=Depends(require('courses.manage'))):
    obj=db.get(Course,id)
    if not obj:raise HTTPException(404,'Curso inexistente')
    changes=body.model_dump(exclude_unset=True)
    reject_nulls(changes, {'course_id','assigned_to_id','campus_course_id'})
    if 'name' in changes and db.scalar(select(Course).where(Course.name==changes['name'],Course.id!=id)):
        raise HTTPException(409,'Nombre de curso duplicado')
    from .models import CourseCatalog
    on_request=changes.pop('price_on_request',None)
    if 'price' in changes and on_request is None:on_request=False
    if on_request is not None:
        meta=db.get(CourseCatalog,id)
        if not meta:meta=CourseCatalog(course_id=id);db.add(meta)
        meta.price_on_request=on_request
    for key,value in changes.items():setattr(obj,key,value)
    db.commit();db.refresh(obj);return obj

@app.get('/api/sales-summary')
def sales_summary(db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not (can(user,'sales.manage') or can(user,'sales.read') or can(user,'sales.own')):raise HTTPException(403,'Sin permiso')
    stmt=select(Sale)
    if user.role=='vendedor':stmt=stmt.join(Lead).where(Lead.assigned_to_id==user.id)
    items=db.scalars(stmt).all()
    totals={}
    for x in items:
        course=db.get(Course,x.course_id)
        currency=course.currency if course else 'ARS'
        if currency not in totals:totals[currency]={'confirmed':0.0,'pending':0.0}
        totals[currency]['confirmed' if x.status=='confirmed' else 'pending']+=float(x.amount)
    return {'total':len(items),'confirmed':sum(x.status=='confirmed' for x in items),'pending':sum(x.status=='pending' for x in items),'totals_by_currency':totals}

@app.get('/api/sales/{id}',response_model=SaleOut)
def sale_detail(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    sale=db.get(Sale,id)
    if not sale:raise HTTPException(404,'Venta inexistente')
    if not (can(user,'sales.manage') or can(user,'sales.read') or (can(user,'sales.own') and db.get(Lead,sale.lead_id).assigned_to_id==user.id)):
        raise HTTPException(403,'Sin permiso')
    return sale

@app.get('/api/vendors',response_model=list[UserOut])
def vendors(db:Session=Depends(get_db),user:User=Depends(require('leads.assign'))):
    return db.scalars(select(User).where(User.role=='vendedor',User.active.is_(True)).order_by(User.full_name)).all()


@app.get('/api/auth/permissions')
def permissions(user:User=Depends(current_user)):
    return sorted(ROLE_PERMISSIONS.get(user.role,set()))

@app.get('/api/notifications')
def notifications(db:Session=Depends(get_db),user:User=Depends(current_user)):
    items=db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.id.desc()).limit(200)).all()
    unread=db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id==user.id,Notification.read.is_(False)))
    return {'unread':unread,'items':[{'id':x.id,'title':x.title,'message':x.message,'lead_id':x.lead_id,'read':x.read,'created_at':x.created_at.replace(tzinfo=timezone.utc)} for x in items]}

@app.post('/api/notifications/{id}/read')
def read_notification(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    item=db.get(Notification,id)
    if not item or item.user_id!=user.id:raise HTTPException(404,'Notificación inexistente')
    item.read=True;db.commit();return {'ok':True}

class TemplateUpdate(BaseModel):
    subject: str=Field(min_length=1,max_length=255)
    body: str=Field(min_length=1,max_length=20000)

@app.get('/api/email-templates')
def templates(db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    return [{'key':x.key,'subject':x.subject,'body':x.body} for x in db.scalars(select(EmailTemplate).order_by(EmailTemplate.key)).all()]

@app.put('/api/email-templates/{key}')
def update_template(key:str,body:TemplateUpdate,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    item=db.get(EmailTemplate,key)
    if not item:raise HTTPException(404,'Plantilla inexistente')
    try:automation.validate_template(body.subject,body.body)
    except ValueError as exc:raise HTTPException(422,str(exc))
    item.subject=body.subject;item.body=body.body;db.commit();return {'ok':True}

@app.get('/api/automation')
def automation_status(db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    from .commercial import rules
    hours=rules(db).followup_hours
    return {'enabled':settings.automation_enabled,'poll_seconds':max(10,settings.automation_poll_seconds),
        'threshold_hours':hours,'email_delivery_enabled':settings.email_delivery_enabled,
        'smtp_configured':bool(settings.smtp_host and settings.smtp_from)}

@app.post('/api/automation/run')
def run_automation(user:User=Depends(require('communications.manage'))):
    return automation.run_once()

@app.get('/api/communications')
def communications(db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    items=db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(200)).all()
    return [{'id':x.id,'kind':x.kind,'recipient':x.recipient,'subject':x.subject,'body':x.body,
        'status':x.status,'created_at':x.created_at.replace(tzinfo=timezone.utc),'attempts':d.attempts if d else 0,
        'error':d.error if d else ''} for x in items for d in [db.get(Delivery,x.id)]]

@app.post('/api/communications/{id}/retry')
def retry_email(id:int,db:Session=Depends(get_db),user:User=Depends(require('communications.manage'))):
    item=db.get(Outbox,id)
    if not item:raise HTTPException(404,'Mensaje inexistente')
    if item.kind not in {*automation.DEFAULT_TEMPLATES,'sequence_email'} or item.status not in {'failed','review'}:
        raise HTTPException(409,'Solo se reintentan emails fallidos o en revisión')
    from . import sequences
    decision=sequences.delivery_decision(db,item)
    if decision=='cancel':
        item.status='cancelled';db.commit();raise HTTPException(409,'El mensaje ya no cumple las condiciones de envío')
    if decision=='hold':raise HTTPException(409,'La secuencia está pausada o falta configurar la URL pública')
    delivery=db.get(Delivery,id)
    if delivery and delivery.attempts>=settings.email_max_attempts:raise HTTPException(409,'Límite de intentos alcanzado')
    item.status='queued';db.commit();return {'ok':True}


from .v5 import router as v5_router
app.include_router(v5_router)

from .v6 import router as v6_router
app.include_router(v6_router)
