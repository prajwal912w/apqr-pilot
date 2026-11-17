from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Numeric, Date, DateTime, ForeignKey, UniqueConstraint, func


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


class User(db.Model):
    _tablename_ = 'users'
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