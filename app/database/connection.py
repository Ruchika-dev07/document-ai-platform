"""
Database connection setup using SQLAlchemy.

Reads DATABASE_URL from .env (see app/core/config.py for how that's
loaded). Provides:
- engine: the actual connection to Postgres
- SessionLocal: used to create a database session per request
- Base: the base class all ORM models inherit from
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/idp_platform")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a database session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()