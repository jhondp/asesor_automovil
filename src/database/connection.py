from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from src.config import settings

engine = create_engine(settings.db_url, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db():
    from src.database.models import Brand, Model, Listing, ListingSnapshot  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()
