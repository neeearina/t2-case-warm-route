from pathlib import Path
from app.db import connect, lock

from app.demo import SEGMENTS


def main():
    with connect() as conn:
        lock(conn)
        conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)')
        for path in sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql')):
            if not conn.execute('SELECT 1 FROM schema_migrations WHERE name=%s', (path.name,)).fetchone():
                conn.execute(path.read_text())
                conn.execute('INSERT INTO schema_migrations VALUES (%s)', (path.name,))
        for source in ('weather', 'transport', 'reports', 'mobility'):
            conn.execute('INSERT INTO source_status(source) VALUES (%s) ON CONFLICT DO NOTHING', (source,))
        for segment in SEGMENTS:
            conn.execute('''INSERT INTO segments VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)
                            ON CONFLICT (id) DO NOTHING''', (segment.id, segment.name, segment.kind, segment.longitude, segment.latitude, segment.criticality))


if __name__ == '__main__':
    main()
