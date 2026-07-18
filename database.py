"""
Sets up the connection to our database.
SQLite for now (one local file, zero setup) -- Day 4 swaps this for Postgres
by changing only DATABASE_URL below. Nothing else in the project needs to change,
which is the whole point of using an ORM.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./billsplitter.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed only for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI calls this per-request via Depends(get_db).
    It opens a DB session, hands it to your endpoint, and closes it
    afterward -- even if the endpoint raises an error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
