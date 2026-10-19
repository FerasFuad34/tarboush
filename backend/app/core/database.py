"""
قاعدة البيانات - SQLite + SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# SQLite يحتاج check_same_thread=False للعمل مع FastAPI
connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """إنشاء الجداول — نستورد النماذج قبل create_all حتى تُسجَّل في الـ metadata"""
    from app import models  # noqa: F401  (تسجيل الجداول)
    Base.metadata.create_all(bind=engine)
