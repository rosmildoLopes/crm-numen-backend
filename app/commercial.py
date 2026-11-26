from datetime import datetime, timezone
from sqlalchemy import select,func,update
from .models import (Lead,User,CommercialTask,CommercialRules,ContactLog,Activity,Outbox,TaskReminderVersion)
from .automation import notify

def rules(db):
    item=db.get(CommercialRules,1)
    if not item:
        item=CommercialRules(id=1,followup_hours=12,auto_assign=False,followup_email=True)
        db.add(item);db.flush()
    return item

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def assign_waiting(db,actor_id=None):
    # Caller holds the shared database worker lease.
    vendors=db.scalars(select(User).where(User.role=='vendedor',User.active.is_(True)).order_by(User.id)).all()
    if not vendors:return 0
    loads={v.id:db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_to_id==v.id,Lead.status.notin_(['compro','no_compro']))) for v in vendors}
    waiting=db.scalars(select(Lead).where(Lead.assigned_to_id.is_(None),Lead.status.notin_(['compro','no_compro'])).order_by(Lead.created_at,Lead.id)).all()
    count=0
    for lead in waiting:
        target=min(loads,key=lambda id:(loads[id],id))
        # Conditional write also protects against a concurrent manual assignment.
        changed=db.execute(update(Lead).where(Lead.id==lead.id,Lead.assigned_to_id.is_(None)).values(assigned_to_id=target)).rowcount
        if not changed:continue
        loads[target]+=1;count+=1
        db.add(Activity(lead_id=lead.id,actor_id=actor_id,action='auto_assigned',detail=f'Vendedor {target}; menor carga activa'))
        notify(db,target,f'auto_assigned:{lead.id}:{datetime.now(timezone.utc).timestamp()}',
            'Nuevo lead asignado',f'{lead.first_name} {lead.last_name}',lead.id)
    return count

def notify_due_tasks(db,now):
    count=0
    for task in db.scalars(select(CommercialTask).where(CommercialTask.status=='pending',CommercialTask.due_at<=now)).all():
        lead=db.get(Lead,task.lead_id)
        owner=db.get(User,task.owner_id)
        if not owner or not owner.active or (owner.role=='vendedor' and lead.assigned_to_id!=owner.id):continue
        revision=db.get(TaskReminderVersion,task.id)
        key=f'task_due:{task.id}'+(f':v{revision.revision}' if revision else '')
        notify(db,owner.id,key,'Tarea vencida',task.title,task.lead_id)
        count+=1
    return count

def cancel_followups(db,lead_id):
    db.execute(update(Outbox).where(Outbox.lead_id==lead_id,Outbox.kind=='followup_12h',Outbox.status=='queued').values(status='cancelled'))
