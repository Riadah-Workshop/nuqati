"""Targeted Overview regression tests using the actual SQLAlchemy models and SQLite.

These execute the production Overview functions without importing main.py's
PostgreSQL-only startup migrations or contacting a production database.
"""
import ast
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select, func, delete, text, bindparam
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.db import Base
from app.models import (Company, Driver, Vehicle, Trip, DrivingEvent, DriverLocation,
                        AppSetting, User)

CODE = Path(__file__).resolve().parent / 'app' / 'main.py'
TREE = ast.parse(CODE.read_text())
NAMES = {'_overview_company_scope', '_overview_utc', '_overview_motion',
         'fleet_overview_motion', 'fleet_overview_daily'}
STMT_NODES = []
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in NAMES:
        node.decorator_list = []
        STMT_NODES.append(node)
    elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                  ('_OVERVIEW_DRIVING_EVENTS', '_OVERVIEW_DRIVING_TYPES') for t in node.targets):
        STMT_NODES.append(node)


def allow(user, *roles):
    if user.role not in roles:
        raise PermissionError('Role not permitted')


def scope(user, company_id):
    if user.role != 'super_admin' and user.company_id != company_id:
        raise PermissionError('Company scope')


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


api = {'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone,
       'select': select, 'func': func, 'delete': delete, 'text': text,
       'bindparam': bindparam, 'Session': Session, 'User': User,
       'Driver': Driver, 'Vehicle': Vehicle, 'Trip': Trip,
       'DriverLocation': DriverLocation, 'DrivingEvent': DrivingEvent,
       'AppSetting': AppSetting, 'HTTPException': HTTPException,
       'Depends': lambda _: None, 'current_user': None, 'get_db': lambda: None,
       'json': json, 'allow': allow, 'scope': scope}
exec(compile(ast.fix_missing_locations(ast.Module(body=STMT_NODES, type_ignores=[])), str(CODE), 'exec'), api)


class OverviewDashboardTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.execute(text('''CREATE TABLE mobile_privacy_audit (
            event_id TEXT PRIMARY KEY, company_id INTEGER, driver_id INTEGER,
            vehicle_id INTEGER, privacy_enabled BOOLEAN, selected_at TIMESTAMP,
            received_at TIMESTAMP)'''))
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.db.add_all([Company(id=1, name='Company 1'), Company(id=2, name='Company 2')])
        self.db.add_all([Driver(id=i, company_id=1 if i <= 6 else 2,
                                full_name=f'Driver {i}', phone='', status='active') for i in range(1, 8)])
        self.db.add_all([Vehicle(id=i, company_id=1 if i <= 6 else 2,
                                 plate_number=f'TST-{i}', make_model='Test', assigned_driver_id=i)
                         for i in range(1, 8)])
        self.db.commit()
        self.super_admin = SimpleNamespace(role='super_admin', company_id=None)
        self.company_admin = SimpleNamespace(role='company_admin', company_id=1)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def sample(self, vehicle_id, speed, seconds_ago=30, accuracy=4, company=1):
        self.db.add(Trip(id=vehicle_id, company_id=company, driver_id=vehicle_id,
                         vehicle_id=vehicle_id, started_at=self.now-timedelta(minutes=10),
                         distance_km=3.5, status='active'))
        self.db.add(DriverLocation(company_id=company, driver_id=vehicle_id,
                                   trip_id=vehicle_id, latitude=26, longitude=50,
                                   accuracy_m=accuracy, speed_kmh=speed,
                                   recorded_at=self.now-timedelta(seconds=seconds_ago)))
        self.db.commit()

    def test_moving_stationary_uncertain_stale_and_privacy(self):
        self.sample(1, 32)  # moving
        self.sample(2, 1)   # stationary
        self.sample(3, 3)   # uncertain
        self.sample(4, 20, seconds_ago=600)  # stale
        self.sample(5, 40)
        self.db.execute(text("INSERT INTO mobile_privacy_audit (event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at,received_at) VALUES ('p1',1,5,5,1,:at,:at)"),
                        {'at': self.now})
        self.db.commit()
        motion = api['_overview_motion'](self.db, 1, now=self.now)
        self.assertEqual((motion['moving'], motion['stationary'], motion['unknown']), (1,1,4))
        self.assertEqual(sum(motion[k] for k in ('moving','stationary','unknown')),6)
        self.assertEqual(api['_overview_motion'](self.db,2,now=self.now)['unknown'],1)

    def test_on_demand_snapshot_fresh_and_older_reading_ignored(self):
        self.db.add(AppSetting(key='live_request:1',value=json.dumps({
            'status': 'completed', 'result': {'driver_id':1,
                'recorded_at': (self.now-timedelta(seconds=25)).isoformat(),
                'speed_kmh': 42, 'accuracy_m': 5}})))
        self.db.add(AppSetting(key='live_request:2',value=json.dumps({
            'status': 'completed', 'result': {'driver_id':2,
                'recorded_at': (self.now-timedelta(minutes=8)).isoformat(),
                'speed_kmh': 50, 'accuracy_m': 5}})))
        self.db.commit()
        motion = api['_overview_motion'](self.db, 1, now=self.now)
        self.assertEqual((motion['moving'], motion['stationary'], motion['unknown']), (1,0,5))

    def test_unique_vehicles_across_days_not_busiest_day(self):
        start = (self.now-timedelta(days=15)).replace(hour=0,minute=0,second=0)
        self.db.add_all([
            Trip(id=200,company_id=1,driver_id=1,vehicle_id=1,
                 started_at=start+timedelta(hours=9),status='completed',distance_km=5),
            Trip(id=201,company_id=1,driver_id=2,vehicle_id=2,
                 started_at=start+timedelta(days=1,hours=9),status='completed',distance_km=6),
        ])
        self.db.commit()
        data = api['fleet_overview_daily'](company_id=1,from_at=start,
            to_at=start+timedelta(days=2),db=self.db,user=self.company_admin)
        self.assertEqual(len(data['days']),2)
        self.assertEqual(max(day['vehicles_with_trips'] for day in data['days']),1)
        self.assertEqual(data['totals']['vehicles_with_trips'],2)
        self.assertEqual([day['vehicles_without_trips'] for day in data['days']], [5,5])

    def test_historical_range_does_not_freeze_motion_and_severe_events_count(self):
        self.sample(1, 20)
        historical_day = self.now-timedelta(days=10)
        old_trip = Trip(id=100, company_id=1, driver_id=1, vehicle_id=1,
                        started_at=historical_day, status='completed', distance_km=11)
        old_trip2 = Trip(id=101, company_id=1, driver_id=1, vehicle_id=1,
                         started_at=historical_day+timedelta(minutes=1), status='active', distance_km=3)
        old_trip3 = Trip(id=102, company_id=1, driver_id=2, vehicle_id=2,
                         started_at=historical_day+timedelta(minutes=2), status='completed', distance_km=7)
        self.db.add_all([old_trip,old_trip2,old_trip3])
        kinds = ['excessive_speeding','excessive_harsh_braking',
                 'excessive_harsh_acceleration','harsh_cornering',
                 'speeding_session','geofence_entry']
        self.db.add_all([DrivingEvent(company_id=1, driver_id=1, trip_id=100,
                                      event_type=kind, value=42, recorded_at=historical_day)
                         for kind in kinds])
        self.db.commit()
        start=historical_day.replace(hour=0, minute=0, second=0)
        end=start+timedelta(days=1)
        data=api['fleet_overview_daily'](company_id=1,from_at=start,to_at=end,
                                         db=self.db,user=self.company_admin)
        self.assertEqual(data['totals']['trips'],3)
        self.assertEqual(data['totals']['vehicles_with_trips'],2)
        self.assertEqual(data['totals']['drivers_active'],2)
        self.assertEqual(data['totals']['distance_km'],21)
        self.assertEqual(data['totals']['violations'],4)
        self.assertEqual([data['days'][0][k] for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')], [1,1,1,1])
        self.assertEqual(len(data['days']),1)
        self.assertEqual(data['motion']['moving'],1)
        # The company manager cannot request another company's report or live motion.
        with self.assertRaises(HTTPException) as ctx:
            api['fleet_overview_motion'](company_id=2,db=self.db,user=self.company_admin)
        self.assertEqual(ctx.exception.status_code,403)

if __name__ == '__main__':
    unittest.main()
