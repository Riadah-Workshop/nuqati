"""Small helpers used by several feature modules that were defined late in the original file."""

from fastapi import HTTPException
from sqlalchemy import select

from ..auth import allow
from ..models import Driver, DriverAccount

def own_driver(db,user):
    allow(user,'driver')
    a=db.scalar(select(DriverAccount).where(DriverAccount.user_id==user.id))
    if not a: raise HTTPException(403,'No driver profile linked to this account')
    d=db.get(Driver,a.driver_id)
    if not d or d.company_id!=user.company_id or d.status!='active': raise HTTPException(403,'Driver disabled or invalid')
    return d

def _company_logo_setting(company_id: int) -> str:
    return f'company_driver_logo:{company_id}'
