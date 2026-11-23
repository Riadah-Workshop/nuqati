"""Isolated DB-free checks for signed driver tokens and lock validation."""
import os
import time
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

os.environ.setdefault('NUQATI_AUTH_SECRET','test-device-session-secret-which-is-long-enough')
from app.auth import encode_token, current_user, refresh_driver_session
from app.models import DriverDeviceSession


class FakeDb:
    def __init__(self, user, session):
        self.user=user
        self.session=session
    def get(self, model, key):
        if model is DriverDeviceSession:return self.session if self.session and self.session.user_id==key else None
        return self.user if self.user.id==key else None


def test_driver_token_requires_session_and_revokes_both_token_types():
    user=SimpleNamespace(id=7,role='driver',auth_version=0,is_active=True)
    try:
        encode_token(user)
        assert False,'Driver token without device binding must be prohibited'
    except ValueError:pass
    session=SimpleNamespace(user_id=7,device_id='secure-install-one',session_id='session-secret-a')
    db=FakeDb(user,session)
    access=encode_token(user,session_id=session.session_id)
    refresh=encode_token(user,refresh=True,session_id=session.session_id)
    credentials=HTTPAuthorizationCredentials(scheme='Bearer',credentials=access)
    assert current_user(creds=credentials,db=db) is user
    assert refresh_driver_session(refresh,db)==(user,session.session_id)
    db.session=None
    for action in (lambda:current_user(creds=credentials,db=db),lambda:refresh_driver_session(refresh,db)):
        try:
            action()
            assert False,'A released device must invalidate its signed tokens immediately'
        except HTTPException as e:
            assert e.status_code==401
    db.session=SimpleNamespace(user_id=7,device_id='secure-install-two',session_id='session-secret-b')
    try:current_user(creds=credentials,db=db);assert False
    except HTTPException as e:assert e.status_code==401


def test_admin_token_is_not_subject_to_driver_device_lock():
    admin=SimpleNamespace(id=3,role='company_admin',auth_version=0,is_active=True)
    access=encode_token(admin)
    cred=HTTPAuthorizationCredentials(scheme='Bearer',credentials=access)
    assert current_user(creds=cred,db=FakeDb(admin,None)) is admin
