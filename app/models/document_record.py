"""
SQLAlchemy ORM model for processed documents.

Matches architecture doc section 13 (Database), extended slightly to
also track which category (JV/Invoice/Supporting Document) and which
batch a record came from, since one upload now produces many records.
"""

from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime
from sqlalchemy.sql import func

from app.database.connection import Base


class DocumentRecord(Base):
    __tablename__ = "document_records"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, index=True)
    page_number = Column(Integer)
    category = Column(String, index=True)  # JV / Invoice / Supporting Document

    invoice_no = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    amount = Column(Numeric, nullable=True)
    invoice_date = Column(Date, nullable=True)
    status = Column(String, default="pending")  # pending / validated / pushed_to_sharepoint

    created_at = Column(DateTime(timezone=True), server_default=func.now())