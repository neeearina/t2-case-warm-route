from app.demo import SEGMENTS
import unittest
from datetime import datetime, timedelta, timezone
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.contracts import Report, StatusChange
from app.mocks import app
from app.scoring import calculate
from app.sources import fetch_weather, fetch_feed


class ScoringTests(unittest.TestCase):
    def test_explanation_and_missing_data(self):
        now = datetime.now(timezone.utc)
        score, info = calculate('ice', .9, now-timedelta(hours=48), now, 2, {})
        self.assertTrue(0 <= score <= 100)
        self.assertEqual(info['factors']['duration'], 1)
        self.assertEqual(len(info['missing_or_stale']), 3)
        self.assertAlmostEqual(score, sum(info['contributions'].values()), places=2)

    def test_mobility_increases_priority(self):
        now = datetime.now(timezone.utc)
        low, _ = calculate('snow', .5, now, now, 1, {'mobility': .1})
        high, _ = calculate('snow', .5, now, now, 1, {'mobility': .9})
        self.assertGreater(high, low)

    def test_blank_status_reason_rejected(self):
        with self.assertRaises(ValidationError):
            StatusChange(status="ACTIVE", reason="   ")

    def test_naive_time_rejected(self):
        with self.assertRaises(ValidationError):
            Report(external_id='x',occurred_at='2026-01-01T12:00:00',latitude=57,longitude=65,category='ice',text='test')


class SourceTests(unittest.TestCase):
    def test_mock_contracts_and_stable_ids(self):
        client = TestClient(app)
        first = fetch_feed(client,'','reports')
        self.assertEqual(first, fetch_feed(client,'','reports'))
        self.assertTrue(first[0].synthetic)
        self.assertEqual(len(fetch_feed(client,'','mobility')), len(SEGMENTS))
        self.assertEqual(len(fetch_feed(client,'','transport')), len(SEGMENTS))
        self.assertEqual(len(fetch_weather(client,'mock','',datetime.now(timezone.utc))),len(SEGMENTS))

    def test_demo_has_three_priority_levels(self):
        now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
        scores = []
        for id_, category, count in ((4, 'ice', 2), (6, 'snow', 1), (8, 'snow', 1)):
            segment = next(s for s in SEGMENTS if s.id == id_)
            score, _ = calculate(category, segment.criticality, now.replace(hour=0), now, count,
                {'weather': segment.weather, 'mobility': segment.mobility,
                 'transport': min(1, segment.delay_minutes / 30)})
            scores.append(score)
        self.assertGreaterEqual(scores[0], 70)
        self.assertTrue(40 <= scores[1] < 70)
        self.assertLess(scores[2], 40)
        records = fetch_feed(TestClient(app), '', 'reports')
        self.assertEqual(len(records), 9)
        self.assertEqual(len({record.external_id for record in records}), 9)

    def test_real_weather_mapping(self):
        now = datetime(2026,1,1,12,30,tzinfo=timezone.utc)
        data = {'hourly_units':{'temperature_2m':'°C','precipitation':'mm','snowfall':'cm'},
                'hourly':{'time':['2026-01-01T12:00'],'temperature_2m':[-3],'precipitation':[1],'snowfall':[1]}}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,json=data))) as client:
            result = fetch_weather(client,'open_meteo','',now)
        self.assertEqual(result[0].value,.9)
        self.assertFalse(result[0].synthetic)
        self.assertEqual(result[0].observed_at.hour,12)

    def test_bad_weather_units_fail(self):
        data = {'hourly_units':{'temperature_2m':'F','precipitation':'mm','snowfall':'cm'}}
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,json=data))) as client:
            with self.assertRaises(ValueError):
                fetch_weather(client,'open_meteo','',datetime.now(timezone.utc))
