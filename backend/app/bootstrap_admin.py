import getpass, os
from sqlalchemy import select
from .db import SessionLocal, Base, engine
from .models import User
from .auth import hash_password

def main():
    Base.metadata.create_all(bind=engine)
    email=input('Super admin email: ').strip().lower()
    name=input('Full name: ').strip()
    password=getpass.getpass('New password (12+ characters): ')
    if '@' not in email or len(name)<2 or len(password)<12: raise SystemExit('Invalid input; no changes made')
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email==email)): raise SystemExit('Email already exists; no changes made')
        db.add(User(email=email,full_name=name,password_hash=hash_password(password),role='super_admin',company_id=None))
    print('Super admin created. Do not share credentials.')
if __name__=='__main__': main()
