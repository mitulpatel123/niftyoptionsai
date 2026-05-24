import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

from config.settings import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

# Global connection pool
_connection_pool = None

def _get_pool():
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=20,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    return _connection_pool

@contextmanager
def get_connection(cursor_factory=RealDictCursor):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        if cursor_factory:
            conn.cursor_factory = cursor_factory
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.cursor_factory = None
        pool.putconn(conn)

