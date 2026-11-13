from app.demo import SEGMENTS
import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from temporalio.exceptions import ApplicationError
from fastapi.testclient import TestClient
from psycopg import sql
from temporalio.client import Client
from temporalio.worker import Worker
from app.api import app
from app.config import settings
from app.contracts import Report
from app.db import connect, lock
from app.init_db import main as init_db
from app.service import submit_report, change_status, refresh, utcnow
from app.workflows import RefreshCity
from app.activities import ingest, maintain


@unittest.skipUnless(os.getenv('RUN_INTEGRATION') == '1', 'requires Compose PostGIS and Temporal')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_url = settings.database_url
        cls.schema = 'test_' + uuid4().hex
        with connect() as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        settings.database_url += '?options=-csearch_path%3D' + cls.schema + ',public'
        init_db()

    @classmethod
    def tearDownClass(cls):
        settings.database_url = cls.original_url
        with connect() as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))

    def report(self, **changes):
        body = dict(external_id=str(uuid4()),occurred_at=utcnow(),latitude=57.145,longitude=65.550,
                    category='snow',text='test '+str(uuid4()))
        body.update(changes)
        return Report(**body)

    def test_00_clean_demo_and_repeat_import(self):
        init_db()
        for source in ('weather', 'mobility', 'transport', 'reports'):
            ingest(source)
        with connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) n FROM segments').fetchone()['n'], 8)
            self.assertEqual(conn.execute('SELECT count(*) n FROM context').fetchone()['n'], 24)
            self.assertEqual(conn.execute('SELECT count(*) n FROM incidents').fetchone()['n'], 9)
            self.assertEqual(conn.execute('SELECT count(*) n FROM signals').fetchone()['n'], 11)
            scores = [row['score'] for row in conn.execute('SELECT score FROM incidents').fetchall()]
            self.assertTrue(any(score < 40 for score in scores))
            self.assertTrue(any(40 <= score < 70 for score in scores))
            self.assertTrue(any(score >= 70 for score in scores))
        for source in ('weather', 'mobility', 'transport', 'reports'):
            ingest(source)
        with connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) n FROM incidents').fetchone()['n'], 9)
            self.assertEqual(conn.execute('SELECT count(*) n FROM signals').fetchone()['n'], 11)

    def test_idempotency_and_conflicting_ids(self):
        report = self.report()
        first = submit_report(report)
        second = submit_report(report)
        self.assertEqual(first['id'], second['id'])
        with self.assertRaises(ValueError):
            submit_report(report.model_copy(update={'text':'changed'}))
        self.assertEqual(first['segment_id'],2)

    def test_unmatched_and_old_reports(self):
        unmatched = submit_report(self.report(latitude=0,longitude=0))
        self.assertIsNone(unmatched['segment_id'])
        old = submit_report(self.report(occurred_at=utcnow()-timedelta(days=2)))
        self.assertIsNone(old['incident_id'])

    def test_status_recheck_closed_and_late_event(self):
        report = self.report(category='ice',latitude=57.160,longitude=65.565)
        id_ = submit_report(report)['incident_id']
        with self.assertRaises(ValueError):
            change_status(id_,'CLOSED','cannot skip verification')
        change_status(id_,'ACTIVE','confirmed')
        change_status(id_,'RESOLVED','work completed')
        with connect() as conn:
            lock(conn)
            conn.execute("UPDATE incidents SET recheck_at=now()-interval '1 minute' WHERE id=%s", (id_,))
            refresh(conn,utcnow())
        result = change_status(id_,'CLOSED','checked on site')
        self.assertEqual(result['score'],0)
        late = submit_report(self.report(category='ice',latitude=57.160,longitude=65.565,occurred_at=report.occurred_at))
        self.assertIsNone(late['incident_id'])
        new = submit_report(self.report(category='ice',latitude=57.160,longitude=65.565))
        self.assertNotEqual(new['incident_id'],id_)

    def test_new_signal_reopens_resolved(self):
        id_ = submit_report(self.report(category='delay',latitude=57.160,longitude=65.565))['incident_id']
        change_status(id_,'ACTIVE','confirmed')
        change_status(id_,'RESOLVED','completed')
        submit_report(self.report(category='delay',latitude=57.160,longitude=65.565))
        with connect() as conn:
            row = conn.execute('SELECT status FROM incidents WHERE id=%s', (id_,)).fetchone()
        self.assertEqual(row['status'],'ACTIVE')

    def test_concurrent_duplicate(self):
        report = self.report()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _:submit_report(report),range(4)))
        self.assertEqual(len({r['id'] for r in results}),1)

    def test_api(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/health').status_code,200)
            self.assertEqual(len(client.get('/segments').json()['items']),len(SEGMENTS))
            self.assertEqual(client.get('/incidents/99999999').status_code,404)
            self.assertEqual(client.post('/reports',json={'text':'missing fields'}).status_code,422)
            self.assertEqual(client.get('/incidents?limit=1000').status_code,422)
            body = self.report().model_dump(mode='json')
            response = client.post('/reports',json=body)
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.post('/reports',json=body).json()['id'],response.json()['id'])

    def test_failed_batch_rolls_back(self):
        valid = self.report()
        invalid = self.report(occurred_at=utcnow()+timedelta(hours=1))
        with patch('app.activities.fetch_feed', return_value=[valid, invalid]):
            with self.assertRaises(ApplicationError):
                ingest('reports')
        with connect() as conn:
            self.assertIsNone(conn.execute('SELECT id FROM signals WHERE external_id=%s', (valid.external_id,)).fetchone())
            self.assertTrue(conn.execute("SELECT last_error FROM source_status WHERE source='reports'").fetchone()['last_error'])

    def test_temporal_workflow_and_retry_safe_replay(self):
        async def run():
            client = await Client.connect(settings.temporal_address)
            queue = 'test-'+uuid4().hex
            with ThreadPoolExecutor(max_workers=4) as executor:
                async with Worker(client,task_queue=queue,workflows=[RefreshCity],activities=[ingest,maintain],activity_executor=executor):
                    first = await client.execute_workflow(RefreshCity.run,id=str(uuid4()),task_queue=queue)
                    with connect() as conn:
                        before = conn.execute('SELECT count(*) n FROM signals').fetchone()['n']
                    second = await client.execute_workflow(RefreshCity.run,id=str(uuid4()),task_queue=queue)
                    with connect() as conn:
                        after = conn.execute('SELECT count(*) n FROM signals').fetchone()['n']
                    self.assertNotIn('failed',first.values())
                    self.assertNotIn('failed',second.values())
                    self.assertEqual(before,after)
                    from app.sources import fetch_feed
                    def faulty_feed(client, url, source):
                        if source == 'reports':
                            raise ValueError('bad feed')
                        return fetch_feed(client, url, source)
                    with patch('app.activities.fetch_feed', side_effect=faulty_feed):
                        failed = await client.execute_workflow(RefreshCity.run,id=str(uuid4()),task_queue=queue)
                    self.assertEqual(failed['reports'],'failed')
                    self.assertNotEqual(failed['mobility'],'failed')
        asyncio.run(run())
