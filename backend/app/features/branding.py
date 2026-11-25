"""Public and admin branding and default labels."""

import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit
from ..auth import allow, current_user
from ..db import get_db
from ..models import AppSetting, User

DEFAULT_LABELS={
 'overview':['Overview','نظرة عامة'],'companies':['Companies','الشركات'],'users':['Users & Access','المستخدمون والصلاحيات'],
 'vehicles':['Vehicles','السيارات'],'drivers':['Drivers','السائقون'],'odometer':['Odometer','قراءة العداد'],
 'maintenance':['Maintenance Alerts','تنبيهات الصيانة'],'reports':['Fleet Reports','تقارير الأسطول'],
 'refresh':['Refresh','تحديث'],'logout':['Log out','خروج'],'brand':['Nuqati by Al-Riadah Workshop','نقاطي من ورشة حلول الريادة لصيانة السيارات'],
 'save':['Save changes','حفظ التغييرات'],'settings':['Branding & Language','الهوية واللغة']}

@app.get('/api/v1/public/branding')
def public_branding(db:Session=Depends(get_db)):
    row=db.get(AppSetting,'branding')
    return json.loads(row.value) if row else {'logo_data':'','labels':{}}

class BrandingIn(BaseModel):
    logo_data: str = Field(default='',max_length=300000)
    labels: dict[str,dict[str,str]] = Field(default_factory=dict)

@app.put('/api/v1/admin/branding')
def update_branding(payload:BrandingIn,db:Session=Depends(get_db),admin:User=Depends(current_user)):
    allow(admin,'super_admin')
    if payload.logo_data and (not payload.logo_data.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')) or len(payload.logo_data)>300000):
        raise HTTPException(422,'Use a PNG, JPEG or WebP logo smaller than 220 KB')
    if len(payload.labels)>100: raise HTTPException(422,'Too many labels')
    cleaned={}
    for key,translations in payload.labels.items():
        if key not in DEFAULT_LABELS: raise HTTPException(422,'Unknown label key: '+key)
        cleaned[key]={lang:value.strip() for lang,value in translations.items() if lang in ('en','ar') and isinstance(value,str) and 0<len(value.strip())<=120}
    data=json.dumps({'logo_data':payload.logo_data,'labels':cleaned},ensure_ascii=False)
    row=db.get(AppSetting,'branding')
    if row: row.value=data
    else: db.add(AppSetting(key='branding',value=data))
    audit(db,'branding.update',actor=admin,target_type='branding',target_id='global')
    db.commit();return {'status':'saved'}

@app.get('/api/v1/public/label-defaults')
def label_defaults():
    return {key:{'en':value[0],'ar':value[1]} for key,value in DEFAULT_LABELS.items()}
