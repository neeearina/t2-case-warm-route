import psycopg
from psycopg.rows import dict_row
from app.config import settings


def connect():
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def lock(conn):
    # A single short transaction serializes mutations in this small MVP.
    conn.execute('SELECT pg_advisory_xact_lock(72901)')
