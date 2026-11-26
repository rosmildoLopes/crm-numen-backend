from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator, model_serializer

class ORM(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    @field_serializer('*',when_used='json')
    def serialize_utc(self,value):
        if isinstance(value,datetime):
            return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()
        return value
class Login(BaseModel):
    # Login identifiers also support the legacy local administrator address.
    email: str=Field(min_length=3,max_length=255)
    password: str
    @field_validator('email')
    @classmethod
    def normalize_identifier(cls,value):return value.strip()
class Token(BaseModel): access_token: str; token_type: str='bearer'
class UserCreate(BaseModel): email: EmailStr; full_name: str; password: str=Field(min_length=8); role: str='vendedor'
class UserOut(ORM): id: int; email: str; full_name: str; role: str; active: bool
class UserUpdate(BaseModel): full_name: str|None=None; role: str|None=None; active: bool|None=None
class CourseCreate(BaseModel): name: str; description: str=''; price: Decimal=Field(default=Decimal('0'),ge=0); currency: str='ARS'; campus_course_id: str|None=None; price_on_request: bool=False
class CourseOut(ORM):
    id: int; name: str; description: str; price: Decimal|None; currency: str; active: bool; campus_course_id: str|None
    price_on_request: bool=False
    school: str=''
    program_type: str=''
    duration: str=''
    @model_serializer(mode='wrap')
    def hide_unquoted_price(self,handler):
        result=handler(self)
        if self.price_on_request:result['price']=None
        return result
class LeadCreate(BaseModel): first_name: str; last_name: str=''; email: EmailStr; phone: str=''; source: str='manual'; course_id: int|None=None
class LeadUpdate(BaseModel): first_name: str|None=None; last_name: str|None=None; email: EmailStr|None=None; phone: str|None=None; source: str|None=None; status: str|None=None; course_id: int|None=None; assigned_to_id: int|None=None
class LeadOut(ORM): id: int; first_name: str; last_name: str; email: str; phone: str; source: str; status: str; course_id: int|None; assigned_to_id: int|None; created_at: datetime
class NoteCreate(BaseModel): text: str=Field(min_length=1)
class NoteOut(ORM): id: int; lead_id: int; author_id: int; text: str; created_at: datetime
class ActivityOut(ORM): id: int; lead_id: int; actor_id: int|None; action: str; detail: str; created_at: datetime
class SaleCreate(BaseModel): lead_id: int; course_id: int; amount: Decimal=Field(gt=0); payment_reference: str
class SaleOut(ORM): id: int; lead_id: int; course_id: int; amount: Decimal; payment_reference: str; status: str
class PaymentConfirm(BaseModel): reference: str

class CourseUpdate(BaseModel):
    price_on_request: bool|None=None
    name: str|None=None
    description: str|None=None
    price: Decimal|None=Field(default=None,ge=0)
    currency: str|None=None
    active: bool|None=None
    campus_course_id: str|None=None
