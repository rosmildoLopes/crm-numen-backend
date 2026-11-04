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
