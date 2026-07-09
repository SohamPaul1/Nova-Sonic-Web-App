"""
Database module for the Nova Sonic newspaper helpdesk agent.

Uses a ThreadedConnectionPool so each query borrows a fresh connection and
returns it when done. This keeps concurrent WebSocket sessions and parallel
tool calls safe (a single shared psycopg2 connection is not) and prevents one
failed query from wedging the whole app in an aborted-transaction state — every
helper commits on success and rolls back on error before returning its
connection to the pool.

Connection parameters come from environment variables (DB_HOST, DB_PORT,
DB_USER, DB_PASSWORD, DB_NAME) loaded by python-dotenv. All read helpers use
RealDictCursor so results are returned as dicts.
"""

import os
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nova_sonic")

# ---------- Connection pool (established once at import) ----------

try:
    pool = ThreadedConnectionPool(
        minconn=1,
        maxconn=int(os.getenv("DB_POOL_MAX", "10")),
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT") or 5432,
    )
    logger.info("✅ PostgreSQL connection pool established.")
except Exception as e:
    logger.exception("Error creating the database connection pool: %s", e)
    raise


@contextmanager
def get_connection():
    """Borrow a connection from the pool and return it when done.

    Commits on clean exit, rolls back on any exception, and always returns the
    connection to the pool so a failed query can never leave it in an aborted
    transaction state that breaks later queries.
    """
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ---------- Query helpers ----------

def fetch_one(query: str, params: tuple = ()):
    """Execute a query and return a single row as a dict, or None."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()


def fetch_all(query: str, params: tuple = ()):
    """Execute a query and return all rows as a list of dicts."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def execute(query: str, params: tuple = ()):
    """Execute a write query and return the number of affected rows."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount


def insert_returning(query: str, params: tuple = ()):
    """Execute an INSERT/UPDATE … RETURNING query and return the row as a dict."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()


# ---------- Lifecycle ----------

def close_db():
    """Close all pooled connections gracefully."""
    try:
        pool.closeall()
        logger.info("PostgreSQL connection pool closed.")
    except Exception as e:
        logger.exception("Error closing PostgreSQL connection pool: %s", e)
