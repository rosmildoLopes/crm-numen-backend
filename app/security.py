from datetime import datetime,timedelta,timezone
import jwt
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
from .models import User
from .config import settings

hasher=PasswordHash.recommended()
bearer=HTTPBearer()
def hash_password(s): return hasher.hash(s)
def verify_password(s,h): return hasher.verify(s,h)
def token_for(user):
    return jwt.encode({'sub':str(user.id),'exp':datetime.now(timezone.utc)+timedelta(minutes=settings.jwt_expire_minutes)},settings.jwt_secret,algorithm='HS256')
def current_user(auth:HTTPAuthorizationCredentials=Depends(bearer),db:Session=Depends(get_db)):
    try:
        payload=jwt.decode(auth.credentials,settings.jwt_secret,algorithms=['HS256'])
        uid=int(payload['sub'])
    except (jwt.PyJWTError,ValueError,KeyError): raise HTTPException(401,'Token inválido')
    user=db.get(User,uid)
    if not user or not user.active: raise HTTPException(401,'Usuario inactivo o inexistente')
    return user

ROLE_PERMISSIONS={
 'super_admin':{'*'},
 'admin':{'users.manage','courses.manage','leads.manage','leads.assign','leads.export','sales.manage','dashboard.all'},
 'direccion_administrativa':{'users.manage','courses.manage','leads.manage','leads.assign','leads.export','sales.manage','dashboard.all'},
 'finanzas':{'sales.manage','dashboard.all','courses.manage','leads.read'},
 'marketing':{'leads.manage','leads.export','courses.manage','dashboard.all'},
 'supervisor_ventas':{'leads.manage','leads.assign','dashboard.all','sales.read'},
 'vendedor':{'leads.own','sales.own'},
 'direccion_academica':{'courses.manage','dashboard.all'},
 'director_carrera':{'courses.manage'},
 'docente':set(), 'tutor':set(), 'contenidista':set()
}
for _role in ('admin','direccion_administrativa','marketing'):
    ROLE_PERMISSIONS[_role].add('communications.manage')

for _role in ('admin','direccion_administrativa','supervisor_ventas','vendedor'):
    ROLE_PERMISSIONS[_role].add('ai.use')

def can(user,permission):
    p=ROLE_PERMISSIONS.get(user.role,set())
    return '*' in p or permission in p or (permission=='leads.read' and ('leads.manage' in p or 'leads.own' in p))
def require(permission):
    def check(user:User=Depends(current_user)):
        if not can(user,permission): raise HTTPException(403,'Sin permiso')
        return user
    return check
