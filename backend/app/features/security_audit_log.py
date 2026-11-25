"""Read access to the security audit trail (`GET /api/v1/security-audit`)."""

from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import User


@app.get('/api/v1/security-audit')
def list_security_audit(company_id: int | None = None, action: str | None = None, actor_user_id: int | None = None,
                        outcome: str | None = None, since: datetime | None = None, limit: int = 100, offset: int = 0,
                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Newest first. Super admins see every company; company admins only their own."""
    allow(user, 'super_admin', 'company_admin')
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, 'Limit must be 1-500 and offset nonnegative')
    if user.role != 'super_admin':
        company_id = user.company_id
    if company_id is not None:
        scope(user, company_id)
    predicates, args = [], {'limit': limit, 'offset': offset}
    for column, name, value in (('company_id', 'cid', company_id), ('action', 'action', action),
                                ('actor_user_id', 'uid', actor_user_id), ('outcome', 'outcome', outcome),
                                ('created_at >=', 'since', since)):
        if value is not None:
            predicates.append(f'{column} :{name}' if column.endswith('>=') else f'{column}=:{name}')
            args[name] = value
    where = 'WHERE ' + ' AND '.join(predicates) if predicates else ''
    rows = db.execute(text(f"""SELECT id,created_at,actor_user_id,actor_email,actor_role,company_id,action,outcome,
        target_type,target_id,ip,detail FROM security_audit {where} ORDER BY id DESC LIMIT :limit OFFSET :offset"""), args).mappings().all()
    return [dict(row) for row in rows]
