import logging
from datetime import timedelta
import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError
from app.config import settings
from app.demo import SEGMENTS
from app.contracts import Context, Report
from app.db import connect, lock
from app.service import ingest_report, refresh, utcnow
from app.sources import fetch_weather, fetch_feed

log = logging.getLogger(__name__)


def save_context(conn, source, sample, now):
    if sample.observed_at > now + timedelta(minutes=5):
        raise ValueError('Context time is in the future')
    conn.execute('''INSERT INTO context(source,segment_id,observed_at,value,synthetic) VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(source,segment_id) DO UPDATE SET observed_at=excluded.observed_at,
        value=excluded.value,synthetic=excluded.synthetic WHERE context.observed_at <= excluded.observed_at''',
        (source,sample.segment_id,sample.observed_at,sample.value,sample.synthetic))


@activity.defn
def ingest(source: str) -> int:
    now = utcnow()
    try:
        if source == 'weather':
            with connect() as conn:
                previous = conn.execute('SELECT last_success FROM source_status WHERE source=%s', (source,)).fetchone()
                cached = conn.execute("SELECT synthetic FROM context WHERE source='weather' LIMIT 1").fetchone()
                expected_ids = [segment.id for segment in SEGMENTS]
                coverage = conn.execute("SELECT count(*) n FROM context WHERE source='weather' AND segment_id=ANY(%s)", (expected_ids,)).fetchone()['n']
                same_provider = cached and cached['synthetic'] == (settings.weather_provider == 'mock') and coverage == len(expected_ids)
                if same_provider and previous and previous['last_success'] and now - previous['last_success'] < timedelta(minutes=30):
                    return 0
        # No network calls inside DB transactions.
        with httpx.Client(timeout=httpx.Timeout(20, connect=5)) as client:
            if source == 'weather':
                rows = fetch_weather(client,settings.weather_provider,settings.mock_url,now)
            else:
                rows = fetch_feed(client, settings.mock_url, source)
        if len(rows) > 100:
            raise ValueError('MVP feed limit exceeded (100 records)')
        with connect() as conn:
            lock(conn)
            for row in rows:
                if source == 'reports':
                    ingest_report(conn, source, row, now)
                elif source == 'transport':
                    save_context(conn, source, Context(segment_id=row.segment_id,observed_at=row.observed_at,value=min(1,row.delay_minutes/30),synthetic=True),now)
                    if row.delay_minutes >= 10:
                        point = conn.execute('SELECT ST_Y(location::geometry) lat, ST_X(location::geometry) lon FROM segments WHERE id=%s', (row.segment_id,)).fetchone()
                        ingest_report(conn,source,Report(external_id=row.external_id,occurred_at=row.observed_at,
                            latitude=point['lat'],longitude=point['lon'],category='delay',
                            text='Модельная задержка транспорта не менее 10 минут',synthetic=True),now)
                else:
                    save_context(conn,source,row,now)
            refresh(conn,now)
            conn.execute('''INSERT INTO source_status VALUES (%s,%s,NULL) ON CONFLICT(source)
                            DO UPDATE SET last_success=excluded.last_success,last_error=NULL''', (source,now))
        log.info('source=%s records=%s', source,len(rows))
        return len(rows)
    except Exception as exc:
        with connect() as conn:
            conn.execute('''INSERT INTO source_status(source,last_error) VALUES (%s,%s)
                ON CONFLICT(source) DO UPDATE SET last_error=excluded.last_error''', (source,str(exc)[:500]))
        permanent = isinstance(exc, (ValueError, KeyError, TypeError)) or (
            isinstance(exc,httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500 and exc.response.status_code != 429)
        raise ApplicationError(str(exc), non_retryable=permanent) from exc


@activity.defn
def maintain() -> None:
    with connect() as conn:
        lock(conn)
        refresh(conn,utcnow())
