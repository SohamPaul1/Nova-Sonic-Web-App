"""
Database connection module for the Nova Sonic newspaper helpdesk agent.

Connects to PostgreSQL once at import time using environment variables
(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME) loaded by python-dotenv
in main.py. All helpers use RealDictCursor so results are returned as dicts.
"""

import os
import logging
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("nova_sonic")

# ---------- Connection (established once at import) ----------

try:
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT") or 5432,
    )
    conn.autocommit = False
    logger.info("PostgreSQL connection established.")
    logger.info("✅ PostgreSQL connection established.")
except Exception as e:
    logger.exception("Error connecting to the database: %s", e)
    logger.error(f"❌ Failed to connect to PostgreSQL: {e}")
    raise


# ---------- Query helpers ----------

def fetch_one(query: str, params: tuple = ()):
    """Execute a query and return a single row as a dict, or None."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchone()


def fetch_all(query: str, params: tuple = ()):
    """Execute a query and return all rows as a list of dicts."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def execute(query: str, params: tuple = ()):
    """Execute a write query, commit, and return the number of affected rows."""
    with conn.cursor() as cur:
        cur.execute(query, params)
        conn.commit()
        return cur.rowcount


def insert_returning(query: str, params: tuple = ()):
    """Execute an INSERT … RETURNING query and return the resulting row as a dict."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        try:
            return cur.fetchone()
        except Exception:
            return None


# ---------- Lifecycle ----------

def close_db():
    """Close the database connection gracefully."""
    try:
        conn.close()
        logger.info("PostgreSQL connection closed.")
        logger.info("PostgreSQL connection closed.")
    except Exception as e:
        logger.exception("Error closing PostgreSQL connection: %s", e)
