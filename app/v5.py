from datetime import datetime,timedelta,timezone
from decimal import Decimal
from typing import Literal
import csv,io,json
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field,field_validator,ValidationError
from sqlalchemy import select,func,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db,SessionLocal
from .models import (User,Lead,Course,Sale,Activity,CommercialTask,ContactLog,CommercialRules,WorkerLock,AIUsage,AIDraft)
from .schemas import LeadCreate
from .security import current_user,require,can
from .commercial import rules,utc,assign_waiting,cancel_followups
from . import automation
from .config import settings

router=APIRouter(prefix='/api')

def get_lead(db,id,user):
    from .main import get_lead as original
    return original(db,id,user)

def edit_lead(db,id,user):
    lead=get_lead(db,id,user)
    if not (can(user,'leads.manage') or can(user,'leads.own')):raise HTTPException(403,'Sin permiso')
    return lead

class TaskCreate(BaseModel):
    lead_id:int
    title:str=Field(min_length=1,max_length=255)
    detail:str=Field(default='',max_length=10000)
    due_at:datetime
    owner_id:int|None=None
    @field_validator('due_at')
    @classmethod
    def timezone_required(cls,value):
        if value.tzinfo is None:raise ValueError('La fecha debe incluir zona horaria')
        return value.astimezone(timezone.utc)
    @field_validator('title')
    @classmethod
    def title_nonblank(cls,value):
        if not value.strip():raise ValueError('El título es obligatorio')
        return value.strip()

class TaskUpdate(BaseModel):
    status:Literal['pending','done','cancelled']

@router.get('/tasks')
def tasks(state:Literal['all','pending','overdue','done','cancelled']='pending',db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can(user,'leads.read'):raise HTTPException(403,'Sin permiso')
    stmt=select(CommercialTask).join(Lead)
    if user.role=='vendedor':stmt=stmt.where(CommercialTask.owner_id==user.id,Lead.assigned_to_id==user.id)
    if state!='all':stmt=stmt.where(CommercialTask.status==('pending' if state=='overdue' else state))
    if state=='overdue':stmt=stmt.where(CommercialTask.due_at<=datetime.now(timezone.utc))
    return [dict(id=t.id,lead_id=t.lead_id,owner_id=t.owner_id,title=t.title,detail=t.detail,due_at=utc(t.due_at),status=t.status,
        lead_name=f'{l.first_name} {l.last_name}',overdue=t.status=='pending' and utc(t.due_at)<=datetime.now(timezone.utc))
        for t in db.scalars(stmt.order_by(CommercialTask.due_at).limit(1000)).all() for l in [db.get(Lead,t.lead_id)]]

@router.post('/tasks',status_code=201)
def create_task(body:TaskCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    lead=edit_lead(db,body.lead_id,user)
    owner_id=body.owner_id or lead.assigned_to_id or user.id
    if owner_id!=user.id and not can(user,'leads.assign'):raise HTTPException(403,'Sin permiso para asignar tareas')
    owner=db.get(User,owner_id)
    if not owner or not owner.active or not can(owner,'leads.read') or (owner.role=='vendedor' and lead.assigned_to_id!=owner.id):
        raise HTTPException(400,'El responsable debe poder acceder al lead')
    item=CommercialTask(**body.model_dump(exclude={'owner_id'}),owner_id=owner_id)
    db.add(item);db.flush()
    db.add(Activity(lead_id=lead.id,actor_id=user.id,action='task_created',detail=f'{item.title}; {body.due_at.isoformat()}'))
    automation.notify(db,owner_id,f'task_created:{item.id}','Nueva tarea',item.title,lead.id)
    db.commit();return {'id':item.id}

@router.patch('/tasks/{id}')
def update_task(id:int,body:TaskUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    item=db.get(CommercialTask,id)
    if not item:raise HTTPException(404,'Tarea inexistente')
    edit_lead(db,item.lead_id,user)
    if item.owner_id!=user.id and not can(user,'leads.assign'):raise HTTPException(403,'Sin permiso')
    if item.status!=body.status:
        db.add(Activity(lead_id=item.lead_id,actor_id=user.id,action='task_updated',detail=f'Tarea {id}: {body.status}'))
    item.status=body.status;db.commit();return {'ok':True}

class ContactCreate(BaseModel):
    channel:Literal['phone','email','whatsapp','meeting','other']
    outcome:Literal['no_answer','replied','interested','not_interested']
    detail:str=Field(min_length=1,max_length=10000)

@router.get('/leads/{id}/contacts')
def contacts(id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    get_lead(db,id,user)
    return [dict(id=x.id,actor_id=x.actor_id,channel=x.channel,outcome=x.outcome,detail=x.detail,created_at=utc(x.created_at))
        for x in db.scalars(select(ContactLog).where(ContactLog.lead_id==id).order_by(ContactLog.id.desc())).all()]

@router.post('/leads/{id}/contacts',status_code=201)
def create_contact(id:int,body:ContactCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    lead=edit_lead(db,id,user)
    db.add(ContactLog(lead_id=id,actor_id=user.id,**body.model_dump()))
    db.add(Activity(lead_id=id,actor_id=user.id,action='contact_logged',detail=f'{body.channel}: {body.outcome}'))
    if body.outcome!='no_answer':
        cancel_followups(db,id)
        from .sequences import stop_for_lead
        stop_for_lead(db,id,'El interesado respondió',user.id)
        if lead.status not in {'compro','no_compro'}:lead.status='no_compro' if body.outcome=='not_interested' else 'contactado'
    db.commit();return {'ok':True}

@router.get('/leads-duplicates')
def duplicates(db:Session=Depends(get_db),user:User=Depends(require('leads.manage'))):
    groups={}
    for l in db.scalars(select(Lead).order_by(Lead.id)).all():
        groups.setdefault(l.email.strip().casefold(),[]).append(dict(id=l.id,name=f'{l.first_name} {l.last_name}',course_id=l.course_id,status=l.status))
    return [{'email':email,'leads':items} for email,items in groups.items() if len(items)>1]

class ImportBody(BaseModel):
    csv_text:str=Field(min_length=1,max_length=1000000)
    commit:bool=False

def parse_import(text):
    try:
        rows=list(csv.DictReader(io.StringIO(text.lstrip('\ufeff')),strict=True))
    except csv.Error:raise HTTPException(422,'CSV inválido')
    if not rows or len(rows)>1000:raise HTTPException(422,'Importar entre 1 y 1000 filas')
    if not {'first_name','email'}.issubset(rows[0]):raise HTTPException(422,'Columnas requeridas: first_name,email')
    return rows

@router.post('/leads-import')
def import_leads(body:ImportBody,db:Session=Depends(get_db),user:User=Depends(require('leads.manage'))):
    rows=parse_import(body.csv_text)
    # The same DB lease serializes imports and automatic assignment across workers.
    now=datetime.now(timezone.utc)
    acquired=db.execute(update(WorkerLock).where(WorkerLock.key=='automation',WorkerLock.expires_at<=now).values(expires_at=now+timedelta(minutes=10))).rowcount
    if not acquired:db.rollback();raise HTTPException(409,'Hay otra operación en curso; intentá nuevamente')
    # Keep this transaction open: import and lease release commit atomically.
    seen={x.strip().casefold() for x in db.scalars(select(Lead.email)).all()}
    results=[];created=0
    try:
        for index,row in enumerate(rows,2):
            try:
                data={k:(row.get(k) or '').strip() for k in ['first_name','last_name','email','phone','source']}
                data['source']=data['source'] or 'csv'
                if not data['first_name']:raise ValueError('Nombre vacío')
                if len(data['first_name'])>120 or len(data['phone'])>50 or len(data['source'])>80:raise ValueError('Campo demasiado largo')
                data['course_id']=int(row['course_id']) if row.get('course_id') else None
                valid=LeadCreate.model_validate(data)
                if valid.course_id and not db.get(Course,valid.course_id):raise ValueError('Curso inexistente')
            except (ValueError,ValidationError):
                results.append({'row':index,'status':'invalid','message':'Revisar nombre, email, curso y longitudes'});continue
            key=str(valid.email).strip().casefold()
            if key in seen:
                results.append({'row':index,'status':'duplicate','message':'Email ya presente en CRM o CSV'});continue
            seen.add(key)
            if body.commit:
                lead=Lead(**valid.model_dump());db.add(lead);db.flush()
                db.add(Activity(lead_id=lead.id,actor_id=user.id,action='imported',detail='Importación CSV V5'))
                # No unsolicited welcome emails are queued by an import.
                created+=1
            results.append({'row':index,'status':'created' if body.commit else 'ready','email':str(valid.email)})
        db.execute(update(WorkerLock).where(WorkerLock.key=='automation').values(expires_at=datetime(2000,1,1,tzinfo=timezone.utc)))
        db.commit()
        return {'committed':body.commit,'created':created,'rows':results}
    except Exception:
        db.rollback();raise

class RulesUpdate(BaseModel):
    followup_hours:int=Field(ge=1,le=720)
    auto_assign:bool
    followup_email:bool

@router.get('/commercial-rules')
def get_rules(db:Session=Depends(get_db),user:User=Depends(require('leads.assign'))):
    r=rules(db);db.commit()
    return {'followup_hours':r.followup_hours,'auto_assign':r.auto_assign,'followup_email':r.followup_email}

@router.put('/commercial-rules')
def set_rules(body:RulesUpdate,db:Session=Depends(get_db),user:User=Depends(require('leads.assign'))):
    r=rules(db)
    for k,v in body.model_dump().items():setattr(r,k,v)
    db.commit();return {'ok':True}

@router.post('/leads-auto-assign')
def auto_assign(db:Session=Depends(get_db),user:User=Depends(require('leads.assign'))):
    now=datetime.now(timezone.utc)
    acquired=db.execute(update(WorkerLock).where(WorkerLock.key=='automation',WorkerLock.expires_at<=now).values(expires_at=now+timedelta(minutes=10))).rowcount
    if not acquired:db.rollback();raise HTTPException(409,'Hay otra ejecución en curso')
    try:
        count=assign_waiting(db,user.id)
        db.execute(update(WorkerLock).where(WorkerLock.key=='automation').values(expires_at=datetime(2000,1,1,tzinfo=timezone.utc)))
        db.commit();return {'assigned':count}
    except Exception:db.rollback();raise

@router.get('/commercial-metrics')
def metrics(dimension:Literal['vendor','course','source']='vendor',db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can(user,'leads.read'):raise HTTPException(403,'Sin permiso')
    stmt=select(Lead)
    if user.role=='vendedor':stmt=stmt.where(Lead.assigned_to_id==user.id)
    leads=db.scalars(stmt).all();groups={}
    courses={c.id:c.name for c in db.scalars(select(Course)).all()}
    vendors={u.id:u.full_name for u in db.scalars(select(User)).all()}
    ids={x.id for x in leads}
    sale_stmt=select(Sale)
    if user.role=='vendedor':sale_stmt=sale_stmt.join(Lead).where(Lead.assigned_to_id==user.id)
    # Marketing may view lead conversion but must not gain sales permission here.
    show_money=any(can(user,p) for p in ['sales.manage','sales.read','sales.own'])
    sales=db.scalars(sale_stmt.where(Sale.status=='confirmed')).all() if show_money else []
    def key(lead):return str(lead.assigned_to_id or '') if dimension=='vendor' else str(lead.course_id or '') if dimension=='course' else lead.source
    for lead in leads:
        k=key(lead)
        if k not in groups:
            label=vendors.get(lead.assigned_to_id,'Sin asignar') if dimension=='vendor' else courses.get(lead.course_id,'Sin curso') if dimension=='course' else lead.source
            groups[k]={'key':k,'label':label,'leads':0,'purchased':0,'conversion':0,'confirmed_sales':0,'revenue':{}}
        g=groups[k];g['leads']+=1;g['purchased']+=int(lead.status=='compro')
    by_id={l.id:l for l in leads}
    for sale in sales:
        if sale.lead_id not in ids:continue
        g=groups[key(by_id[sale.lead_id])];g['confirmed_sales']+=1
        c=db.get(Course,sale.course_id);currency=c.currency if c else 'ARS'
        g['revenue'][currency]=g['revenue'].get(currency,Decimal('0'))+sale.amount
    for g in groups.values():g['conversion']=round(g['purchased']/g['leads']*100,1)
    return {'dimension':dimension,'money_visible':show_money,'items':sorted(groups.values(),key=lambda x:(-x['leads'],x['label']))}

class AIInput(BaseModel):
    text:str=Field(min_length=1,max_length=12000)
    share_data:bool=False

@router.get('/ai/status')
def ai_status(user:User=Depends(require('ai.use'))):
    return {'enabled':settings.ai_enabled,'configured':bool(settings.openai_api_key and settings.openai_model),
        'model':settings.openai_model,'daily_call_limit':max(0,settings.ai_daily_call_limit)}

@router.post('/leads/{id}/ai-draft')
def ai_draft(id:int,body:AIInput,db:Session=Depends(get_db),user:User=Depends(require('ai.use'))):
    lead=get_lead(db,id,user)
    if not body.share_data:raise HTTPException(422,'Confirmá el envío del texto y contexto al proveedor de IA')
    if settings.demo_mode or not settings.ai_enabled or not settings.openai_api_key or not settings.openai_model:raise HTTPException(503,'IA sin configurar o deshabilitada')
    # Atomic per-user daily reservation, including failed calls. No automatic retries.
    key=f'{user.id}:{datetime.now(timezone.utc).date().isoformat()}'
    if not db.get(AIUsage,key):
        try:db.add(AIUsage(key=key,calls=0));db.commit()
        except IntegrityError:db.rollback()
    accepted=db.execute(update(AIUsage).where(AIUsage.key==key,AIUsage.calls<max(0,settings.ai_daily_call_limit)).values(calls=AIUsage.calls+1)).rowcount
    db.commit()
    if not accepted:raise HTTPException(429,'Límite diario de solicitudes alcanzado')
    course=db.get(Course,lead.course_id) if lead.course_id else None
    context={'status':lead.status,'course':{'name':course.name,'description':course.description,'price':None if course.price_on_request else str(course.price),'price_on_request':course.price_on_request,'currency':course.currency} if course else None,'consultation':body.text}
    from .ai import generate
    result=generate(context)
    item=AIDraft(lead_id=id,user_id=user.id,result=json.dumps(result,ensure_ascii=False),model=settings.openai_model)
    db.add(item);db.add(Activity(lead_id=id,actor_id=user.id,action='ai_draft',detail='Borrador generado; no enviado'))
    db.commit();return result
