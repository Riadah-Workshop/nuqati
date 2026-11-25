"""Manager-facing list of unreachable-driver alerts."""

from fastapi import Depends
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import current_user
from ..connectivity_alerts import list_connection_alerts
from ..db import get_db
from ..models import User

@app.get('/api/v1/fleet/connection-alerts')
def fleet_connection_alerts(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return list_connection_alerts(db,user,company_id)
