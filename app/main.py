from contextlib import asynccontextmanager
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
    yield

app=FastAPI(title='Academia Numen CRM API',version='0.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def audit(db,lead_id,actor_id,action,detail=''):
    db.add(Activity(lead_id=lead_id,actor_id=actor_id,action=action,detail=detail))
def lead_access(lead,user):
    if not can(user,'leads.manage') and not can(user,'leads.read'):
        raise HTTPException(403,'Sin permiso')
    if user.role=='vendedor' and lead.assigned_to_id!=user.id: raise HTTPException(403,'Lead no asignado')

def get_lead(db,id,user):
    lead=db.get(Lead,id)
    if not lead: raise HTTPException(404,'Lead inexistente')
    lead_access(lead,user)
    return lead

@app.get('/health')
def health(): return {'status':'ok'}
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
    obj=Course(**body.model_dump());db.add(obj);db.commit();db.refresh(obj);return obj

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
    course=db.get(Course,body.course_id) if body.course_id else None
    db.add(Outbox(lead_id=obj.id,kind='welcome_lead',recipient=obj.email,subject='Recibimos tu consulta - Academia Numen',body=f'Hola {obj.first_name}, recibimos tu consulta sobre {course.name if course else "nuestros cursos"}. Pronto te contactaremos.'))
    db.commit();db.refresh(obj);return obj
@app.get('/api/leads/{id}',response_model=LeadOut)
def lead_detail(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):return get_lead(db,id,user)
@app.patch('/api/leads/{id}',response_model=LeadOut)
def update_lead(id:int,body:LeadUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    obj=get_lead(db,id,user);changes=body.model_dump(exclude_unset=True)
    if not can(user,'leads.manage') and any(k not in {'status','phone','first_name','last_name'} for k in changes):raise HTTPException(403,'No autorizado')
    if 'assigned_to_id' in changes and not can(user,'leads.assign'):raise HTTPException(403,'No puede asignar')
    if 'status' in changes and changes['status'] not in STATUSES:raise HTTPException(400,'Estado inválido')
    if 'status' in changes and changes['status']=='compro':raise HTTPException(400,'La compra se confirma desde pagos')
    if changes.get('course_id') and not db.get(Course,changes['course_id']):raise HTTPException(400,'Curso inválido')
    if changes.get('assigned_to_id'):
        target=db.get(User,changes['assigned_to_id'])
        if not target or not target.active or target.role!='vendedor':raise HTTPException(400,'Vendedor inválido')
    for k,v in changes.items():setattr(obj,k,v)
    audit(db,id,user.id,'updated',str(changes));db.commit();db.refresh(obj);return obj
@app.post('/api/leads/{id}/notes',response_model=NoteOut,status_code=201)
def add_note(id:int,body:NoteCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user)
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
    return {'total_leads':len(items),'unassigned':sum(x.assigned_to_id is None for x in items),'by_status':{s:sum(x.status==s for x in items) for s in sorted(STATUSES)},'overdue_unassigned':sum(x.assigned_to_id is None and x.created_at.replace(tzinfo=timezone.utc)<datetime.now(timezone.utc)-timedelta(hours=12) for x in items)}

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
    audit(db,lead.id,user.id,'payment_manually_confirmed',f'Venta {sale.id}')
    db.add(Outbox(lead_id=lead.id,kind='campus_enrollment_pending',recipient=lead.email,subject='Matrícula pendiente de integración',body=f'Venta {sale.id} confirmada manualmente. Integrar Campus antes de habilitar accesos.'))
    db.commit();db.refresh(sale);return sale
@app.get('/api/outbox')
def outbox(db:Session=Depends(get_db),user:User=Depends(require('dashboard.all'))):
    return [{'id':x.id,'kind':x.kind,'recipient':x.recipient,'status':x.status,'subject':x.subject} for x in db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(100)).all()]
