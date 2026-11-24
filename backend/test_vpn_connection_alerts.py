"""DB-free regression tests for the 60s/300s/15min connectivity policy."""
from datetime import datetime, timedelta, timezone
from email import message_from_string
from types import SimpleNamespace

from app import connectivity_alerts as alerts


def test_15_minute_server_received_heartbeat_threshold():
    now = datetime(2026,11,24,8,0,tzinfo=timezone.utc)
    assert alerts.POLL_SECONDS == 60
    assert alerts.OFFLINE_SECONDS == 900
    assert alerts.EMAIL_RETRY_SECONDS == 300
    assert not alerts.is_overdue(now - timedelta(seconds=899), now)
    assert alerts.is_overdue(now - timedelta(seconds=900), now)
    assert alerts.is_overdue(now - timedelta(hours=3), now)
    # Naive values from a database are treated consistently as UTC.
    assert alerts.is_overdue((now-timedelta(seconds=900)).replace(tzinfo=None),now)


class _Db:
    def __init__(self):
        self.params=None
    def execute(self,stmt,params):
        self.params=params
        return SimpleNamespace(mappings=lambda:SimpleNamespace(all=lambda:[]))


def test_company_user_cannot_change_alert_scope():
    db=_Db()
    account=SimpleNamespace(role='fleet_manager',company_id=8)
    assert alerts.list_connection_alerts(db, account, company_id=91)==[]
    assert db.params=={'cid':8}
    db2=_Db()
    admin=SimpleNamespace(role='super_admin',company_id=None)
    assert alerts.list_connection_alerts(db2, admin, company_id=None)==[]
    assert db2.params is None  # Explicit company selection required.
    assert alerts.list_connection_alerts(db2, admin, company_id=3)==[]
    assert db2.params=={'cid':3}


def test_manager_email_recipients_hidden(monkeypatch):
    monkeypatch.setenv('NUQATI_SMTP_HOST','mail.test')
    monkeypatch.setenv('NUQATI_SMTP_USER','bot')
    monkeypatch.setenv('NUQATI_SMTP_PASSWORD','do-not-print')
    calls=[]
    class FakeSMTP:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def starttls(self,**kwargs):pass
        def login(self,*args):pass
        def send_message(self,msg,to_addrs):calls.append((msg,to_addrs))
    monkeypatch.setattr(alerts.smtplib,'SMTP',FakeSMTP)
    alerts._send_manager_email(['admin@company.com','fleet@company.com'],'Connection lost','No heartbeat')
    assert len(calls)==1
    msg,addresses=calls[0]
    assert addresses==['admin@company.com','fleet@company.com']
    assert 'admin@company.com' not in str(msg)
    assert 'fleet@company.com' not in str(msg)
    assert msg['From'].startswith('Nuqati <')
