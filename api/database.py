"""
SalesCoach AI — Database connection helper
==========================================
Provides a reusable database connection for API endpoints.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()


def get_db():
    """
    Yields a psycopg2 connection with RealDictCursor.
    Used as a FastAPI dependency.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def get_raw_connection():
    """Returns a plain connection (not a generator) for non-dependency usage."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(db_url, cursor_factory=RealDictCursor)
