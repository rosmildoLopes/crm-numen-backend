from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Boolean, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    full_name: Mapped[str]=mapped_column(String(255))
    password_hash: Mapped[str]=mapped_column(String(255))
    role: Mapped[str]=mapped_column(String(40),default='vendedor')
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Course(Base):
    __tablename__='courses'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(255),unique=True)
    description: Mapped[str]=mapped_column(Text,default='')
    price: Mapped[float]=mapped_column(Numeric(12,2),default=0)
    currency: Mapped[str]=mapped_column(String(3),default='ARS')
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    campus_course_id: Mapped[str|None]=mapped_column(String(100),nullable=True)
    catalog_metadata: Mapped["CourseCatalog"]=relationship(uselist=False)
    @property
    def price_on_request(self):return bool(self.catalog_metadata and self.catalog_metadata.price_on_request)
    @property
    def school(self):return self.catalog_metadata.school if self.catalog_metadata else ''
    @property
    def program_type(self):return self.catalog_metadata.program_type if self.catalog_metadata else ''
    @property
    def duration(self):return self.catalog_metadata.duration if self.catalog_metadata else ''


# Commercial catalogue details are additive; legacy prices remain stored unchanged.
class CourseCatalog(Base):
    __tablename__='course_catalog'
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),primary_key=True)
    price_on_request: Mapped[bool]=mapped_column(Boolean,default=False)
    school: Mapped[str]=mapped_column(String(255),default='')
    program_type: Mapped[str]=mapped_column(String(50),default='')
    duration: Mapped[str]=mapped_column(String(120),default='')
    curriculum_json: Mapped[str]=mapped_column(Text,default='{}')

class DemoRecord(Base):
    __tablename__='demo_records'
    __table_args__=(UniqueConstraint('namespace','kind','external_key'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    namespace: Mapped[str]=mapped_column(String(80))
    kind: Mapped[str]=mapped_column(String(60))
    external_key: Mapped[str]=mapped_column(String(120))
    row_id: Mapped[int]=mapped_column()

class Lead(Base):
    __tablename__='leads'
    id: Mapped[int]=mapped_column(primary_key=True)
    first_name: Mapped[str]=mapped_column(String(120))
    last_name: Mapped[str]=mapped_column(String(120),default='')
    email: Mapped[str]=mapped_column(String(255),index=True)
    phone: Mapped[str]=mapped_column(String(50),default='')
    source: Mapped[str]=mapped_column(String(80),default='manual')
    status: Mapped[str]=mapped_column(String(50),default='recibido')
    course_id: Mapped[int|None]=mapped_column(ForeignKey('courses.id'),nullable=True)
    assigned_to_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    course: Mapped[Course|None]=relationship()
    assigned_to: Mapped[User|None]=relationship()

class LeadNote(Base):
    __tablename__='lead_notes'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id',ondelete='CASCADE'))
    author_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    text: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Activity(Base):
    __tablename__='activities'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'))
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    action: Mapped[str]=mapped_column(String(60))
    detail: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Sale(Base):
    __tablename__='sales'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'))
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'))
    amount: Mapped[float]=mapped_column(Numeric(12,2))
    payment_reference: Mapped[str]=mapped_column(String(255),unique=True)
    status: Mapped[str]=mapped_column(String(30),default='pending')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Outbox(Base):
    __tablename__='outbox'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int|None]=mapped_column(ForeignKey('leads.id'),nullable=True)
    kind: Mapped[str]=mapped_column(String(60))
    recipient: Mapped[str]=mapped_column(String(255))
    subject: Mapped[str]=mapped_column(String(255),default='')
    body: Mapped[str]=mapped_column(Text,default='')
    status: Mapped[str]=mapped_column(String(30),default='queued')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


# V4 adds tables only: existing V3 columns and records are preserved.
class EmailTemplate(Base):
    __tablename__='email_templates'
    key: Mapped[str]=mapped_column(String(60),primary_key=True)
    subject: Mapped[str]=mapped_column(String(255))
    body: Mapped[str]=mapped_column(Text)

class Notification(Base):
    __tablename__='notifications'
    __table_args__=(UniqueConstraint('user_id','event_key'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    lead_id: Mapped[int|None]=mapped_column(ForeignKey('leads.id'),nullable=True)
    event_key: Mapped[str]=mapped_column(String(120))
    title: Mapped[str]=mapped_column(String(255))
    message: Mapped[str]=mapped_column(Text)
    read: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class AutomationEvent(Base):
    __tablename__='automation_events'
    key: Mapped[str]=mapped_column(String(120),primary_key=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class WorkerLock(Base):
    __tablename__='worker_locks'
    key: Mapped[str]=mapped_column(String(60),primary_key=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class Delivery(Base):
    __tablename__='email_deliveries'
    outbox_id: Mapped[int]=mapped_column(ForeignKey('outbox.id'),primary_key=True)
    attempts: Mapped[int]=mapped_column(default=0)
    error: Mapped[str]=mapped_column(Text,default='')
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)


class CommercialTask(Base):
    __tablename__='commercial_tasks'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'),index=True)
    owner_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    title: Mapped[str]=mapped_column(String(255))
    detail: Mapped[str]=mapped_column(Text,default='')
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ContactLog(Base):
    __tablename__='contact_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'),index=True)
    actor_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    channel: Mapped[str]=mapped_column(String(30))
    outcome: Mapped[str]=mapped_column(String(40))
    detail: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class CommercialRules(Base):
    __tablename__='commercial_rules'
    id: Mapped[int]=mapped_column(primary_key=True,default=1)
    followup_hours: Mapped[int]=mapped_column(default=12)
    auto_assign: Mapped[bool]=mapped_column(Boolean,default=False)
    followup_email: Mapped[bool]=mapped_column(Boolean,default=True)

class AIUsage(Base):
    __tablename__='ai_usage'
    key: Mapped[str]=mapped_column(String(80),primary_key=True)
    calls: Mapped[int]=mapped_column(default=0)

class AIDraft(Base):
    __tablename__='ai_drafts'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'))
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    result: Mapped[str]=mapped_column(Text)
    model: Mapped[str]=mapped_column(String(100))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


# V6 is additive: preferences are shared by normalized recipient email.
class EmailPreference(Base):
    __tablename__='email_preferences'
    email: Mapped[str]=mapped_column(String(255),primary_key=True)
    consent: Mapped[str]=mapped_column(String(20),default='unknown')
    blocked: Mapped[bool]=mapped_column(Boolean,default=False)
    source: Mapped[str]=mapped_column(String(120),default='')
    evidence: Mapped[str]=mapped_column(Text,default='')
    updated_by: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class PreferenceHistory(Base):
    __tablename__='preference_history'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255),index=True)
    lead_id: Mapped[int|None]=mapped_column(ForeignKey('leads.id'),nullable=True)
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    consent: Mapped[str]=mapped_column(String(20))
    blocked: Mapped[bool]=mapped_column(Boolean)
    source: Mapped[str]=mapped_column(String(120))
    evidence: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class EmailSequence(Base):
    __tablename__='email_sequences'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(160))
    description: Mapped[str]=mapped_column(Text,default='')
    state: Mapped[str]=mapped_column(String(20),default='draft')
    created_by: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class SequenceStep(Base):
    __tablename__='sequence_steps'
    __table_args__=(UniqueConstraint('sequence_id','position'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    sequence_id: Mapped[int]=mapped_column(ForeignKey('email_sequences.id'),index=True)
    position: Mapped[int]=mapped_column()
    delay_hours: Mapped[int]=mapped_column()
    subject: Mapped[str]=mapped_column(String(255))
    body: Mapped[str]=mapped_column(Text)

class SequenceEnrollment(Base):
    __tablename__='sequence_enrollments'
    __table_args__=(UniqueConstraint('sequence_id','lead_id'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    sequence_id: Mapped[int]=mapped_column(ForeignKey('email_sequences.id'),index=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'),index=True)
    recipient: Mapped[str]=mapped_column(String(255),index=True)
    state: Mapped[str]=mapped_column(String(20),default='active')
    next_position: Mapped[int]=mapped_column(default=1)
    next_due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    reason: Mapped[str]=mapped_column(String(255),default='')
    created_by: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class SequenceDispatch(Base):
    __tablename__='sequence_dispatches'
    __table_args__=(UniqueConstraint('enrollment_id','step_id'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    enrollment_id: Mapped[int]=mapped_column(ForeignKey('sequence_enrollments.id'),index=True)
    step_id: Mapped[int]=mapped_column(ForeignKey('sequence_steps.id'))
    outbox_id: Mapped[int]=mapped_column(ForeignKey('outbox.id'),unique=True)
    sent_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class UnsubscribeToken(Base):
    __tablename__='unsubscribe_tokens'
    token_hash: Mapped[str]=mapped_column(String(64),primary_key=True)
    email: Mapped[str]=mapped_column(String(255),index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

class TaskReminderVersion(Base):
    __tablename__='task_reminder_versions'
    task_id: Mapped[int]=mapped_column(ForeignKey('commercial_tasks.id'),primary_key=True)
    revision: Mapped[int]=mapped_column(default=0)
