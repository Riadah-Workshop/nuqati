"""Server command for two-step sign-in: the way back in when nobody in the dashboard can reset an account.

    docker exec -it <api container> python -m app.mfa_tools status person@example.com
    docker exec -it <api container> python -m app.mfa_tools reset person@example.com

`reset` removes the person's enrolment and recovery codes and ends their sessions (the same as the "Reset two-step
sign-in" button of a super admin, which is the normal way). Use the command when the last super admin lost the
authenticator and the recovery codes. It needs shell access to the server and nothing else; it writes one row to the
security audit trail (action auth.mfa_reset, "via": "server command"). The person signs in with the password and,
if their role requires it, sets two-step sign-in up again.
"""
import sys

from sqlalchemy import text

from . import mfa_db
from .audit import audit
from .db import SessionLocal

USAGE = "usage: python -m app.mfa_tools [status | reset] EMAIL"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("status", "reset") or not argv[1].strip():
        print(USAGE, file=sys.stderr)
        return 2
    action, email = argv[0], argv[1].strip().lower()
    with SessionLocal() as db:
        row = db.execute(text("SELECT id, role, company_id FROM users WHERE email=:email"), {"email": email}).mappings().first()
        if not row:
            print(f"No account with the address {email}.")
            return 1
        enrolled = mfa_db.is_enrolled(db, row["id"])
        if action == "status":
            print(f"{email}: role {row['role']}, two-step sign-in is {'ON' if enrolled else 'off'}.")
            return 0
        mfa_db.reset(db, row["id"])
        audit(db, "auth.mfa_reset", outcome="ok", target_type="user", target_id=row["id"], company_id=row["company_id"],
              detail={"via": "server command", "was_enrolled": enrolled})
        db.commit()
        print(f"Two-step sign-in removed for {email}; their sessions ended." if enrolled
              else f"{email} had no two-step sign-in; nothing to remove (their sessions were ended anyway).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
