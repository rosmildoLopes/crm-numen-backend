from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

class ORM(BaseModel): model_config=ConfigDict(from_attributes=True)
class Login(BaseModel): email: EmailStr; password: str
class Token(BaseModel): access_token: str; token_type: str='bearer'
class UserCreate(BaseModel): email: EmailStr; full_name: str; password: str=Field(min_length=8); role: str='vendedor'
class UserOut(ORM): id: int; email: str; full_name: str; role: str; active: bool
class UserUpdate(BaseModel): full_name: str|None=None; role: str|None=None; active: bool|None=None
class CourseCreate(BaseModel): name: str; description: str=''; price: Decimal=Field(default=Decimal('0'),ge=0); currency: str='ARS'; campus_course_id: str|None=None
class CourseOut(ORM): id: int; name: str; description: str; price: Decimal; currency: str; active: bool; campus_course_id: str|None
class LeadCreate(BaseModel): first_name: str; last_name: str=''; email: EmailStr; phone: str=''; source: str='manual'; course_id: int|None=None
class LeadUpdate(BaseModel): first_name: str|None=None; last_name: str|None=None; email: EmailStr|None=None; phone: str|None=None; source: str|None=None; status: str|None=None; course_id: int|None=None; assigned_to_id: int|None=None
class LeadOut(ORM): id: int; first_name: str; last_name: str; email: str; phone: str; source: str; status: str; course_id: int|None; assigned_to_id: int|None; created_at: datetime
class NoteCreate(BaseModel): text: str=Field(min_length=1)
class NoteOut(ORM): id: int; lead_id: int; author_id: int; text: str; created_at: datetime
class ActivityOut(ORM): id: int; lead_id: int; actor_id: int|None; action: str; detail: str; created_at: datetime
class SaleCreate(BaseModel): lead_id: int; course_id: int; amount: Decimal=Field(gt=0); payment_reference: str
class SaleOut(ORM): id: int; lead_id: int; course_id: int; amount: Decimal; payment_reference: str; status: str
class PaymentConfirm(BaseModel): reference: str
