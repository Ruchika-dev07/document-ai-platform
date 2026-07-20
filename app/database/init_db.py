"""
Run this once to create all tables in the database.

Usage: python3 -m app.database.init_db
"""

from app.database.connection import engine, Base
from app.models.document_record import DocumentRecord  # noqa: F401 - import registers the table


def init_db():
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")


if __name__ == "__main__":
    init_db()