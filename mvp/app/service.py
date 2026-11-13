from datetime import datetime, timedelta, timezone
from psycopg.types.json import Jsonb
from app.config import settings
from app.contracts import Report
from app.db import connect, lock
from app.scoring import calculate


def utcnow():
    return datetime.now(timezone.utc)


def transition(conn, incident_id, status, now, reason):
    conn.execute('UPDATE incidents SET status=%s, updated_at=%s WHERE id=%s', (status, now, incident_id))
    conn.execute('INSERT INTO transitions(incident_id,status,changed_at,reason) VALUES (%s,%s,%s,%s)',
                 (incident_id, status, now, reason))


def ingest_report(conn, source, report: Report, now):
    if report.occurred_at > now + timedelta(minutes=5):
        raise ValueError('Event time is in the future')
    existing = conn.execute('SELECT * FROM signals WHERE source=%s AND external_id=%s',
                            (source, report.external_id)).fetchone()
    if existing:
        # Minimal feed contract: IDs identify immutable events.
        expected = (report.occurred_at, report.latitude, report.longitude, report.category, report.text, report.synthetic)
        actual = tuple(existing[k] for k in ('occurred_at','latitude','longitude','category','text','synthetic'))
        if actual != expected:
            raise ValueError('Event ID reused with different content')
        return existing
    candidates = conn.execute('''SELECT id, ST_Distance(location, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography) distance
        FROM segments WHERE ST_DWithin(location,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,150)
        ORDER BY distance LIMIT 2''', (report.longitude, report.latitude, report.longitude, report.latitude)).fetchall()
    segment_id = candidates[0]['id'] if candidates and (len(candidates) == 1 or candidates[1]['distance'] - candidates[0]['distance'] > 20) else None
    incident = None
    if segment_id:
        incident = conn.execute("SELECT * FROM incidents WHERE segment_id=%s AND category=%s AND status <> 'CLOSED'",
                                (segment_id, report.category)).fetchone()
        last_closed = conn.execute('SELECT max(closed_at) t FROM incidents WHERE segment_id=%s AND category=%s',
                                   (segment_id, report.category)).fetchone()['t']
        # Old events are retained as signals but cannot reopen a closed episode.
        is_current = report.occurred_at >= now - timedelta(hours=24) and (not last_closed or report.occurred_at > last_closed)
        if not is_current:
            incident = None
        elif not incident:
            incident = conn.execute('''INSERT INTO incidents(segment_id,category,status,started_at,updated_at)
                 VALUES (%s,%s,'VERIFYING',%s,%s) RETURNING *''',
                 (segment_id, report.category, report.occurred_at, now)).fetchone()
            transition(conn, incident['id'], 'VERIFYING', now, 'Новый сигнал: требуется подтверждение')
        elif incident['status'] in ('RESOLVED', 'RECHECK') and report.occurred_at > incident['resolved_at']:
            transition(conn, incident['id'], 'ACTIVE', now, 'Новый сигнал после сообщения об устранении')
            conn.execute('UPDATE incidents SET recheck_at=NULL WHERE id=%s', (incident['id'],))
    return conn.execute('''INSERT INTO signals(source,external_id,occurred_at,segment_id,incident_id,category,text,latitude,longitude,synthetic)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
        (source, report.external_id, report.occurred_at, segment_id, incident['id'] if incident else None,
         report.category, report.text, report.latitude, report.longitude, report.synthetic)).fetchone()


def refresh(conn, now):
    due = conn.execute("SELECT id FROM incidents WHERE status='RESOLVED' AND recheck_at <= %s", (now,)).fetchall()
    for row in due:
        transition(conn, row['id'], 'RECHECK', now, 'Срок повторной проверки: требуется подтверждение диспетчера')
    incidents = conn.execute('''SELECT i.*, s.criticality FROM incidents i JOIN segments s ON s.id=i.segment_id
                                WHERE i.status <> 'CLOSED' ''').fetchall()
    for incident in incidents:
        rows = conn.execute('SELECT * FROM context WHERE segment_id=%s', (incident['segment_id'],)).fetchall()
        fresh = {r['source']: r['value'] for r in rows if now - timedelta(hours=2) <= r['observed_at'] <= now}
        # Identical copied reports do not count as independent confirmations.
        count = conn.execute('''SELECT count(DISTINCT (source,lower(trim(text)))) n FROM signals
                                WHERE incident_id=%s AND occurred_at >= %s''',
                             (incident['id'], now - timedelta(hours=24))).fetchone()['n']
        score, explanation = calculate(incident['category'], incident['criticality'], incident['started_at'], now, count, fresh)
        explanation['sources'] = [{**r, 'observed_at': r['observed_at'].isoformat()} for r in rows]
        explanation['synthetic_signals'] = conn.execute('SELECT coalesce(bool_or(synthetic),false) v FROM signals WHERE incident_id=%s', (incident['id'],)).fetchone()['v']
        conn.execute('UPDATE incidents SET score=%s, explanation=%s WHERE id=%s', (score, Jsonb(explanation), incident['id']))


def submit_report(report):
    now = utcnow()
    with connect() as conn:
        lock(conn)
        signal = ingest_report(conn, 'manual', report, now)
        refresh(conn, now)
        return signal


def change_status(incident_id, status, reason):
    now = utcnow()
    with connect() as conn:
        lock(conn)
        row = conn.execute('SELECT * FROM incidents WHERE id=%s', (incident_id,)).fetchone()
        if not row:
            raise LookupError('Incident not found')
        allowed = {'VERIFYING': {'ACTIVE'}, 'ACTIVE': {'RESOLVED'}, 'RESOLVED': {'ACTIVE', 'RECHECK'}, 'RECHECK': {'ACTIVE', 'CLOSED'}, 'CLOSED': set()}
        if status not in allowed[row['status']]:
            raise ValueError(f"Transition {row['status']} -> {status} is not allowed")
        transition(conn, incident_id, status, now, reason)
        if status == 'RESOLVED':
            conn.execute('UPDATE incidents SET resolved_at=%s,recheck_at=%s WHERE id=%s',
                         (now, now + timedelta(seconds=settings.recheck_seconds), incident_id))
        elif status == 'CLOSED':
            conn.execute('UPDATE incidents SET closed_at=%s,recheck_at=NULL,score=0 WHERE id=%s', (now, incident_id))
            conn.execute("UPDATE incidents SET explanation=explanation || %s WHERE id=%s", (Jsonb({'closed': True, 'score_before_close': row['score']}), incident_id))
        else:
            conn.execute('UPDATE incidents SET recheck_at=NULL WHERE id=%s', (incident_id,))
        refresh(conn, now)
        return conn.execute('SELECT * FROM incidents WHERE id=%s', (incident_id,)).fetchone()
