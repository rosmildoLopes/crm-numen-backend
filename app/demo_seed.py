"""Local demonstrator data. No external services and no deletion of existing rows.

Call populate() within a transaction. Registry keys make repeat runs additive and
idempotent, and prevent the script from adopting unrelated records by mistake.
"""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from sqlalchemy import select,func,inspect
from .models import (User,Course,CourseCatalog,Lead,LeadNote,Activity,Sale,Outbox,
    CommercialTask,ContactLog,Notification,Delivery,CommercialRules,EmailPreference,
    PreferenceHistory,EmailSequence,SequenceStep,SequenceEnrollment,SequenceDispatch,
    DemoRecord,AIDraft)
from .security import hash_password
from .config import settings

NAMESPACE='numen-demo-2027-v1'

def populate(db,catalog,password):
    if not settings.demo_mode:raise ValueError('Activar DEMO_MODE=true antes de cargar ejemplos')
    programs=catalog['programs']
    if len(programs)!=41:raise ValueError('Se esperan los 41 programas revisados')
    now=datetime.now(timezone.utc)
    created={}
    def ensure(kind,key,model,factory):
        record=db.scalar(select(DemoRecord).where(DemoRecord.namespace==NAMESPACE,
            DemoRecord.kind==kind,DemoRecord.external_key==str(key)))
        if record:
            obj=db.get(model,record.row_id)
            if not obj:raise ValueError(f'El ejemplo {kind}/{key} fue eliminado. Revisar antes de recrearlo.')
            return obj
        obj=factory();db.add(obj);db.flush()
        row_id=inspect(obj).identity[0]
        db.add(DemoRecord(namespace=NAMESPACE,kind=kind,external_key=str(key),row_id=row_id))
        db.flush();created[kind]=created.get(kind,0)+1
        return obj
    admin=db.scalar(select(User).where(User.email==settings.admin_email))
    if not admin:admin=db.scalar(select(User).where(User.active.is_(True),User.role=='super_admin').order_by(User.id))
    if not admin:raise ValueError('Debe existir un administrador antes de cargar la demostración')
    users=[]
    profiles=[('vendedor1','[DEMO] Lucía Torres','vendedor'),('vendedor2','[DEMO] Martín Vega','vendedor'),
        ('vendedor3','[DEMO] Sofía Ríos','vendedor'),('supervisor','[DEMO] Pablo Méndez','supervisor_ventas'),
        ('marketing','[DEMO] Valentina Cruz','marketing'),('finanzas','[DEMO] Diego Soto','finanzas'),
        ('academica','[DEMO] Carolina Paz','direccion_academica')]
    for code,name,role in profiles:
        def user_factory(code=code,name=name,role=role):
            email=f'demo.{code}@example.com'
            if db.scalar(select(User.id).where(User.email==email)):raise ValueError('El email de ejemplo ya existe sin registro de demostración: '+email)
            return User(email=email,full_name=name,role=role,password_hash=hash_password(password),active=True)
        users.append(ensure('user',code,User,user_factory))
    courses=[]
    for program in programs:
        def course_factory(program=program):
            if db.scalar(select(Course.id).where(Course.name==program['name'])):raise ValueError('Ya existe un programa sin registro de demostración: '+program['name'])
            modules='\n'.join(f"{m['number']}. {m['name']}" for m in program['modules'])
            objective=program['objective'].split(' Perfil de ingreso:')[0]
            description=f"Catálogo 2027 · {program['type']}\nEscuela: {program['school_name']}\nDuración orientativa: {program['duration_indicative']}\n\n{objective}\n\nMódulos propuestos:\n{modules}\n\nTemario sujeto a validación académica. Precio a consultar; no representa una oferta gratuita."
            return Course(name=program['name'],description=description,price=Decimal('0'),currency='ARS',active=True,campus_course_id=None)
        course=ensure('course',program['code'],Course,course_factory);courses.append(course)
        ensure('course_catalog',program['code'],CourseCatalog,lambda c=course,p=program:CourseCatalog(course_id=c.id,
            price_on_request=True,school=p['school_name'],program_type=p['type'],duration=p['duration_indicative'],
            curriculum_json=json.dumps(p,ensure_ascii=False)))
    names=[('Camila','Fernández'),('Nicolás','Medina'),('Florencia','López'),('Tomás','Suárez'),('Julieta','Ramos'),('Mateo','Castro'),
        ('Agustina','Díaz'),('Santiago','Herrera'),('Micaela','Romero'),('Joaquín','Silva'),('Valeria','Molina'),('Lucas','Navarro'),
        ('Emilia','Acosta'),('Bruno','Pereyra'),('Paula','Morales'),('Franco','Ortiz'),('Victoria','Giménez'),('Gabriel','Arias'),
        ('Marina','Benítez'),('Iván','Campos'),('Clara','Núñez'),('Sebastián','Vidal'),('Renata','Ferrer'),('Andrés','Luna'),
        ('Daniela','Ibarra'),('Felipe','Sosa'),('Elena','Rojas'),('Matías','Leiva'),('Catalina','Vera'),('Federico','Cabrera'),
        ('Abril','Ponce'),('Lautaro','Mansilla'),('Josefina','Reyes'),('Ignacio','Miranda'),('Ana','Peralta'),('Ramiro','Costa')]
    statuses=['recibido','pendiente_contacto','contactado','pensando','no_compro','compro']
    sources=['DEMO · formulario web','DEMO · redes sociales','DEMO · referido','DEMO · consulta directa']
    leads=[]
    for i,(first,last) in enumerate(names):
        status=statuses[i%6];seller=None if i in {0,1,6,7,12,13,18,19} else users[i%3].id
        hours=(2 if i==0 else 7 if i==1 else 18+i*3)
        course=courses[(i*7)%41]
        lead=ensure('lead',i+1,Lead,lambda i=i,first=first,last=last,status=status,seller=seller,hours=hours,course=course:
            Lead(first_name='[DEMO] '+first,last_name=last,email=f'demo.lead{i+1:02d}@example.com',phone='',
                source=sources[i%len(sources)],status=status,course_id=course.id,assigned_to_id=seller,
                created_at=now-timedelta(hours=hours),updated_at=now-timedelta(hours=max(0,hours-3))))
        leads.append(lead)
        ensure('activity_created',i+1,Activity,lambda l=lead:Activity(lead_id=l.id,actor_id=admin.id,action='demo_lead_created',
            detail='Registro ficticio para recorrer el CRM. No corresponde a una persona ni consulta real.',created_at=l.created_at))
        ensure('note',i+1,LeadNote,lambda l=lead,c=course:LeadNote(lead_id=l.id,author_id=l.assigned_to_id or users[3].id,
            text=f'DEMO: consulta simulada por {c.name}. Revisar objetivos, disponibilidad y modalidad. Precio del catálogo a consultar.',created_at=l.created_at+timedelta(hours=1)))
        if status in {'contactado','pensando','no_compro','compro'}:
            outcome='not_interested' if status=='no_compro' else 'interested' if status in {'pensando','compro'} else 'replied'
            ensure('contact',i+1,ContactLog,lambda l=lead,i=i,outcome=outcome:ContactLog(lead_id=l.id,actor_id=l.assigned_to_id or users[3].id,
                channel=['phone','email','whatsapp','meeting'][i%4],outcome=outcome,
                detail='DEMO: conversación ficticia. El interesado solicita información del programa y próximos pasos. No se realizó una llamada ni se envió un mensaje real.',created_at=now-timedelta(hours=4+i)))
        if i<12:
            consent='withdrawn' if i in {4,10} else 'granted'
            ensure('preference_history',i+1,PreferenceHistory,lambda l=lead,consent=consent:PreferenceHistory(email=l.email,
                lead_id=l.id,actor_id=admin.id,consent=consent,blocked=consent=='withdrawn',source='DEMO: autorización simulada',
                evidence='Ejemplo ficticio, no consentimiento de una persona real.'))
            # Preferences use a string primary key; do not overwrite any preexisting preference.
            if not db.get(EmailPreference,lead.email):db.add(EmailPreference(email=lead.email,consent=consent,blocked=consent=='withdrawn',
                source='DEMO: autorización simulada',evidence='Ejemplo ficticio para presentación local.',updated_by=admin.id))
    for i,lead in enumerate([l for l in leads if l.status in {'compro','pensando'}]):
        confirmed=lead.status=='compro'
        sale=ensure('sale',i+1,Sale,lambda i=i,l=lead,confirmed=confirmed:Sale(lead_id=l.id,course_id=l.course_id,
            amount=Decimal([39000,65000,78000,95000,120000,145000][i%6]),payment_reference=f'DEMO-2027-{i+1:03d}',
            status='confirmed' if confirmed else 'pending',created_at=now-timedelta(days=1+i%5)))
        ensure('activity_sale',i+1,Activity,lambda l=lead,s=sale:Activity(lead_id=l.id,actor_id=users[5].id,
            action='demo_sale_recorded',detail=f'DEMO: venta #{s.id} e importe ficticios. No es un precio del catálogo ni un pago bancario verificado.'))
        if confirmed:
            ensure('campus_event',sale.id,Outbox,lambda l=lead,s=sale:Outbox(lead_id=l.id,kind='campus_enrollment_pending',recipient=l.email,
                subject='[DEMO] Ejemplo de matrícula pendiente',body=f'DEMO: evento ficticio de venta {s.payment_reference}. No se creó ninguna matrícula.',status='queued'))
    pool=[l for l in leads if l.status not in {'compro','no_compro'}]
    titles=['Llamar para conocer objetivos','Enviar propuesta para revisión','Confirmar disponibilidad horaria','Revisar interés en el programa','Programar próxima conversación']
    for i in range(20):
        lead=pool[i%len(pool)];status='pending' if i<10 else 'done' if i<16 else 'cancelled'
        due_at=now-timedelta(hours=2+i*2) if i<4 else now+timedelta(hours=(i-3)*6)
        ensure('task',i+1,CommercialTask,lambda i=i,l=lead,status=status,due_at=due_at:CommercialTask(lead_id=l.id,
            owner_id=l.assigned_to_id or users[3].id,title='[DEMO] '+titles[i%5],
            detail='Tarea ficticia para recorrer pendientes, vencidas, completadas y canceladas. No contactar personas reales.',
            due_at=due_at,status=status,created_at=now-timedelta(days=2)))
    for i,status in enumerate(['queued','failed','review','cancelled','sent','queued']):
        lead=leads[i]
        message=ensure('email_example',i+1,Outbox,lambda i=i,l=lead,status=status:Outbox(lead_id=l.id,kind='welcome_lead',recipient=l.email,
            subject=f'[DEMO] Ejemplo de comunicación {i+1}',body='DEMO: mensaje y estado de entrega simulados. No hubo envío real. El catálogo tiene precio a consultar.',
            status=status,created_at=now-timedelta(hours=6+i)))
        ensure('delivery',i+1,Delivery,lambda m=message,status=status:Delivery(outbox_id=m.id,attempts=0 if status in {'queued','cancelled'} else 1,
            error='DEMO: resultado ficticio de entrega; no se contactó a un servidor SMTP.'))
    sequences=[];step_sets=[]
    for i,state in enumerate(['active','paused']):
        sequence=ensure('sequence',i+1,EmailSequence,lambda i=i,state=state:EmailSequence(name=['[DEMO] Consulta inicial y orientación','[DEMO] Seguimiento de propuesta'][i],
            description='Secuencia ficticia para presentación. Sin envío real.',state=state,created_by=admin.id))
        sequences.append(sequence);steps=[]
        for pos,delay in enumerate(([0,24,48] if i==0 else [12,48]),1):
            steps.append(ensure('sequence_step',f'{i+1}:{pos}',SequenceStep,lambda seq=sequence,pos=pos,delay=delay:SequenceStep(sequence_id=seq.id,
                position=pos,delay_hours=delay,subject=f'[DEMO] Paso {pos}: tu consulta en Numen',
                body='Hola {first_name}, este es un ejemplo ficticio de seguimiento sobre {course_name}. Precio a consultar.')))
        step_sets.append(steps)
    scenarios=[(0,leads[0],'active',1,''),(1,leads[7],'active',1,''),(0,leads[2],'stopped',1,'DEMO: el interesado respondió'),(1,leads[3],'completed',3,'DEMO: historial de dos pasos completado')]
    for i,(seq_index,lead,state,position,reason) in enumerate(scenarios):
        seq=sequences[seq_index]
        enrollment=ensure('enrollment',i+1,SequenceEnrollment,lambda l=lead,seq=seq,state=state,position=position,reason=reason:SequenceEnrollment(
            sequence_id=seq.id,lead_id=l.id,recipient=l.email,state=state,next_position=position,
            next_due_at=now+timedelta(hours=1),reason=reason,created_by=admin.id,created_at=now-timedelta(days=3)))
        positions=[1,2] if state=='completed' else [1]
        for pos in positions:
            status='sent' if state=='completed' else 'cancelled' if state=='stopped' else 'queued'
            message=ensure('sequence_message',f'{i+1}:{pos}',Outbox,lambda l=lead,pos=pos,status=status:Outbox(lead_id=l.id,kind='sequence_email',recipient=l.email,
                subject=f'[DEMO] Paso {pos} de seguimiento',body='DEMO: estado simulado para recorrer el CRM. No hubo envío real. Precio a consultar.',status=status,
                created_at=now-timedelta(days=2)))
            ensure('dispatch',f'{i+1}:{pos}',SequenceDispatch,lambda e=enrollment,s=step_sets[seq_index][pos-1],m=message,state=state:SequenceDispatch(
                enrollment_id=e.id,step_id=s.id,outbox_id=m.id,sent_at=now-timedelta(days=1) if state=='completed' else None))
    for i,title in enumerate(['Consultas pendientes de asignación','Hay tareas de demostración vencidas','Catálogo 2027 cargado','Propuesta de venta pendiente de revisión','Ejemplo de seguimiento pausado','Demostración lista para recorrer']):
        for owner in [admin.id,users[i%4].id]:
            ensure('notification',f'{i}:{owner}',Notification,lambda i=i,title=title,owner=owner:Notification(user_id=owner,lead_id=leads[i].id,
                event_key=f'{NAMESPACE}:notice:{i}:{owner}',title='[DEMO] '+title,
                message='Aviso ficticio para mostrar la bandeja y el contador de notificaciones.',read=i%3==0,created_at=now-timedelta(hours=i)))
    if not db.get(CommercialRules,1):db.add(CommercialRules(id=1,followup_hours=12,auto_assign=False,followup_email=True))
    db.flush()
    return {'created':created,'namespace':NAMESPACE,'courses':len(courses),'leads':len(leads),
            'users':[{'id':u.id,'email':u.email,'role':u.role} for u in users],
            'counts':{model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [Course,Lead,User,Sale,CommercialTask,ContactLog,Outbox,Notification,EmailSequence,SequenceEnrollment]},
            'external_services':'disabled by DEMO_MODE','catalog_pricing':'on_request'}
