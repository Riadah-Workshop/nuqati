"""Creates disposable data for the GPS load test (ops/loadtest/gps_load.py) and prints it as JSON on stdout.

Run it inside the API image so it uses the application's own models and token signing:

    docker run --rm --network <net> -e DATABASE_URL=... -e NUQATI_AUTH_SECRET=... -e NUQATI_LOADTEST_DISPOSABLE=1 \
        -e PYTHONPATH=/app -v $PWD/ops/loadtest/seed.py:/tmp/seed.py:ro nuqati-api:ci python /tmp/seed.py --drivers 600

It writes one company with N drivers (each with a user, a device session, a vehicle and an active trip that started three
hours ago) and a few company administrators. It refuses to run unless NUQATI_LOADTEST_DISPOSABLE=1 is set, because it must
never be pointed at the production database. Nothing is deleted afterwards: the database is thrown away with its container.
"""
import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--drivers', type=int, required=True)
    parser.add_argument('--admins', type=int, default=3)
    args = parser.parse_args(argv)
    if os.environ.get('NUQATI_LOADTEST_DISPOSABLE') != '1':
        print('Refusing to run: set NUQATI_LOADTEST_DISPOSABLE=1 to confirm that DATABASE_URL is a throw-away database.',
              file=sys.stderr)
        return 2
    if not 1 <= args.drivers <= 5000 or not 1 <= args.admins <= 50:
        print('--drivers must be 1..5000 and --admins 1..50', file=sys.stderr)
        return 2

    from app.auth import encode_token
    from app.db import SessionLocal
    from app.models import Company, Driver, DriverAccount, DriverDeviceSession, Trip, User, Vehicle

    suffix = secrets.token_hex(4)
    started = datetime.now(timezone.utc) - timedelta(hours=3)
    with SessionLocal() as db:
        company = Company(name='LOADTEST ' + suffix)
        db.add(company)
        db.flush()
        drivers = [Driver(company_id=company.id, full_name=f'Load driver {i} {suffix}', phone='', status='active')
                   for i in range(args.drivers)]
        db.add_all(drivers)
        db.flush()
        # One placeholder for everyone: these accounts are never used to sign in, only to carry signed tokens.
        users = [User(company_id=company.id, role='driver', full_name=d.full_name, is_active=True,
                      email=f'lt{i}-{suffix}@loadtest.invalid', password_hash='load-test-accounts-cannot-sign-in')
                 for i, d in enumerate(drivers)]
        db.add_all(users)
        db.flush()
        sessions = [secrets.token_hex(16) for _ in users]
        db.add_all([DriverAccount(driver_id=d.id, user_id=u.id) for d, u in zip(drivers, users)])
        db.add_all([DriverDeviceSession(user_id=u.id, device_id='loadtest-' + suffix, session_id=sid)
                    for u, sid in zip(users, sessions)])
        vehicles = [Vehicle(company_id=company.id, plate_number=f'LT{suffix}-{i}', assigned_driver_id=d.id)
                    for i, d in enumerate(drivers)]
        db.add_all(vehicles)
        db.flush()
        trips = [Trip(company_id=company.id, driver_id=d.id, vehicle_id=v.id, status='active', started_at=started)
                 for d, v in zip(drivers, vehicles)]
        db.add_all(trips)
        admins = [User(company_id=company.id, role='company_admin', full_name=f'Load admin {i} {suffix}', is_active=True,
                       email=f'lta{i}-{suffix}@loadtest.invalid', password_hash='load-test-accounts-cannot-sign-in')
                  for i in range(args.admins)]
        db.add_all(admins)
        db.flush()
        result = {
            'company_id': company.id,
            'drivers': [{'token': encode_token(u, session_id=sid), 'trip_id': t.id}
                        for u, sid, t in zip(users, sessions, trips)],
            'admin_tokens': [encode_token(a) for a in admins],
        }
        db.commit()
    json.dump(result, sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
