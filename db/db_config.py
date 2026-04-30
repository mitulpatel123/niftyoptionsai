import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


def get_connection(cursor_factory=RealDictCursor):
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=cursor_factory,
    )

