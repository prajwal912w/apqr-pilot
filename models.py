from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (Column, Integer, String, Numeric, Date, DateTime, ForeignKey,
                        UniqueConstraint, CheckConstraint, func)


db = SQLAlchemy()


class Product(db.Model):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)


class Upload(db.Model):
    __tablename__ = 'uploads'
    id = Column(Integer, primary_key=True)
    filename = Column(String, nullable=False)
    file_hash = Column(String(64), nullable=False, unique=True)
    uploaded_at = Column(DateTime, nullable=False, server_default=func.now())
    # who uploaded the file (nullable only because older rows pre-date this column)
    uploaded_by = Column(Integer, ForeignKey('user.id'), nullable=True)


class Batch(db.Model):
    __tablename__ = 'batches'
    id = Column(Integer, primary_key=True)
    batch_no = Column(String, nullable=False)
    mfg_date = Column(Date, nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    upload_id = Column(Integer, ForeignKey('uploads.id'), nullable=False)
    __table_args__ = (UniqueConstraint('product_id', 'batch_no'),)


class Result(db.Model):
    __tablename__ = 'results'
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey('batches.id'), nullable=False)
    parameter = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    result = Column(Numeric, nullable=False)
    lsl = Column(Numeric, nullable=True)
    usl = Column(Numeric, nullable=True)
    # constraint names must match schema.sql, which adds them to existing databases
    __table_args__ = (
        UniqueConstraint('batch_id', 'parameter', name='results_batch_param_uq'),
        CheckConstraint('lsl IS NOT NULL OR usl IS NOT NULL', name='results_has_limit'),
        CheckConstraint('lsl IS NULL OR usl IS NULL OR lsl <= usl', name='results_lsl_le_usl'),
    )


class User(db.Model):
    # table name defaults to 'user' - that is what the live database already has
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    action = Column(String, nullable=False)
    detail = Column(String, nullable=False)
    at = Column(DateTime, nullable=False, server_default=func.now())
    prev_hash = Column(String, nullable=False)
    entry_hash = Column(String, nullable=False)
