"""In-memory smoke/regression checks for the additive concept report suite."""
from datetime import date, datetime, timezone, timedelta
from io import BytesIO
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from .app.db import Base
from .app.models import Company, Driver, DriverMetadata, Vehicle, Trip, DriverLocation, DrivingEvent
from .app.concept_reports import _dataset, _excel, _csv, _pdf


class ConceptReportTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite+pysqlite:///:memory:')
        Base.metadata.create_all(self.engine,tables=[
            Company.__table__,Driver.__table__,DriverMetadata.__table__,Vehicle.__table__,
            Trip.__table__,DriverLocation.__table__,DrivingEvent.__table__])
        self.db=Session(self.engine)
        self.db.add_all([
          Company(id=9,name='Test fleet'),Driver(id=5,company_id=9,full_name='Ahmad',phone='',status='active'),
          DriverMetadata(driver_id=5,id_number='123',site_name='Khobar depot'),
          Vehicle(id=30,company_id=9,plate_number='AA-123',make_model='Sedan',assigned_driver_id=5),
          Vehicle(id=31,company_id=9,plate_number='BB-456',make_model='Truck'),
          Trip(id=40,company_id=9,driver_id=5,vehicle_id=30,status='completed',distance_km=11.25,
               started_at=datetime(2026,11,15,6,0,tzinfo=timezone.utc),ended_at=datetime(2026,11,15,6,20,tzinfo=timezone.utc)),
          Trip(id=41,company_id=9,driver_id=5,vehicle_id=30,status='completed',distance_km=10,
               started_at=datetime(2026,11,16,7,0,tzinfo=timezone.utc),ended_at=datetime(2026,11,16,7,15,tzinfo=timezone.utc)),
          Trip(id=42,company_id=9,driver_id=5,vehicle_id=30,status='active',distance_km=99,
               started_at=datetime(2026,11,16,10,0,tzinfo=timezone.utc)),
          DriverLocation(id=1,company_id=9,driver_id=5,trip_id=40,latitude=26.3,longitude=50.2,accuracy_m=7,speed_kmh=60,recorded_at=datetime(2026,11,15,6,0,tzinfo=timezone.utc)),
          DriverLocation(id=2,company_id=9,driver_id=5,trip_id=40,latitude=26.31,longitude=50.21,accuracy_m=5,speed_kmh=62,recorded_at=datetime(2026,11,15,6,0,8,tzinfo=timezone.utc)),
          DrivingEvent(id=11,company_id=9,driver_id=5,trip_id=40,event_type='harsh_braking',value=7,recorded_at=datetime(2026,11,15,6,10,tzinfo=timezone.utc)),
        ])
        self.db.commit()
        self.deps={
          'thresholds':lambda db,cid:type('Settings',(),{'speeding_kmh':100.0})(),
          'score_policy':lambda db,cid:{},
          'flexible_rag_policy':lambda db,cid:{'enabled':False},
          'calculate_safety_score':lambda events,km,policy,speed_limit,**kw:{'score':95.0 if km>0 else None},
        }
    def tearDown(self):
        self.db.close();self.engine.dispose()
    def fetch(self,kind, start=date(2026,11,15),end=date(2026,11,21),driver=None,vehicle=None):
        return _dataset(self.db,9,kind,start,end,driver,vehicle,self.deps)

    def test_movement_and_gps_observation(self):
        d=self.fetch('movement')
        self.assertEqual(len(d['rows']),2)
        row=d['rows'][0]
        self.assertEqual(row['distance'],11.25)
        self.assertEqual(row['moving'],'00:00:08')
        self.assertEqual(row['stationary'],'00:00:00')
        self.assertEqual(row['elapsed'],'00:20:00')
        self.assertEqual(row['date'],'2026-11-15')
        self.assertEqual(row['trip_gap'],'24:40:00')
        self.assertIn('26.30000',row['depart_from'])

    def test_daily_trip_fuel_absent(self):
        rows=self.fetch('daily-trips')['rows']
        self.assertEqual(len(rows),2)
        self.assertIsNone(rows[0]['fuel_l'])
        self.assertIsNone(rows[0]['km_per_l'])
        self.assertEqual(rows[0]['trips'],1)
        self.assertEqual(rows[0]['site'],'Khobar depot')

    def test_utilization_weekend_and_inactive(self):
        d=self.fetch('utilization');self.assertEqual(len(d['rows']),2)
        one=d['rows'][0]
        self.assertEqual(one['days_with_trips'],2)
        self.assertEqual(one['days_without_trips'],5)
        self.assertEqual(one['weekday_km'],21.25)
        self.assertEqual(one['weekend_km'],0)
        self.assertEqual(d['rows'][1]['distance'],0)
        self.assertEqual(len(self.fetch('utilization',driver=5)['rows']),1)

    def test_rag_uses_callback_not_reference_score(self):
        d=self.fetch('daily-rag')
        self.assertEqual(d['rows'][0]['hb'],1)
        self.assertAlmostEqual(d['rows'][0]['hb_100'],8.89,places=2)
        self.assertEqual(d['rows'][0]['score'],95)
        self.assertEqual(d['rows'][0]['rag'],'green')

    def test_filters_and_exports(self):
        self.assertEqual(self.fetch('movement',vehicle=31)['rows'],[])
        self.assertEqual(self.fetch('movement',driver=5)['summary']['trips'],2)
        for kind in ('movement','daily-trips','utilization','daily-rag'):
            d=self.fetch(kind)
            self.assertTrue(_excel(d,'en').startswith(b'PK'))
            self.assertTrue(_csv(d,'ar').startswith(b'\xef\xbb\xbf'))
            self.assertTrue(_pdf(d).startswith(b'%PDF'))

if __name__=='__main__':unittest.main()
