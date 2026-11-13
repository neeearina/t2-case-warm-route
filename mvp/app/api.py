from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from app.contracts import Report, StatusChange
from app.db import connect
from app.service import submit_report, change_status

app = FastAPI(title='Тёплый маршрут — MVP', version='0.1.0')


@app.get('/health')
def health():
    with connect() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok'}


@app.get('/segments')
def segments():
    with connect() as conn:
        rows = conn.execute('SELECT id,name,kind,criticality,ST_Y(location::geometry) latitude,ST_X(location::geometry) longitude FROM segments ORDER BY id').fetchall()
    return {'items': rows, 'geography': 'illustrative_demo'}


@app.get('/incidents')
def incidents(status: Literal['VERIFYING','ACTIVE','RESOLVED','RECHECK','CLOSED'] | None = None,
              limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    with connect() as conn:
        if status:
            rows = conn.execute('SELECT * FROM incidents WHERE status=%s ORDER BY score DESC,id LIMIT %s OFFSET %s', (status,limit,offset)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM incidents ORDER BY score DESC,id LIMIT %s OFFSET %s', (limit,offset)).fetchall()
        return {'items': rows}


@app.get('/incidents/{incident_id}')
def incident(incident_id: int):
    with connect() as conn:
        row = conn.execute('SELECT * FROM incidents WHERE id=%s', (incident_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Incident not found')
        row['signals'] = conn.execute('SELECT * FROM signals WHERE incident_id=%s ORDER BY id', (incident_id,)).fetchall()
        row['history'] = conn.execute('SELECT status,changed_at,reason FROM transitions WHERE incident_id=%s ORDER BY id', (incident_id,)).fetchall()
        return row


@app.patch('/incidents/{incident_id}/status')
def update_status(incident_id: int, change: StatusChange):
    try:
        return change_status(incident_id, change.status, change.reason)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/reports')
def report(body: Report):
    try:
        return submit_report(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get('/signals')
def signals(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    with connect() as conn:
        return {'items': conn.execute('SELECT * FROM signals ORDER BY id DESC LIMIT %s OFFSET %s', (limit,offset)).fetchall()}


@app.get('/sources')
def sources():
    with connect() as conn:
        return {'items': conn.execute("SELECT *, (last_success IS NULL OR last_success < now() - interval '2 hours') stale FROM source_status ORDER BY source").fetchall()}


# The compiled dashboard shares the API origin: no extra web server or CORS.
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[1] / 'web' / 'dist'
if WEB.is_dir():
    app.mount('/assets', StaticFiles(directory=WEB / 'assets'), name='assets')

    @app.get('/', include_in_schema=False)
    def dashboard():
        return FileResponse(WEB / 'index.html', headers={'Cache-Control': 'no-cache'})
