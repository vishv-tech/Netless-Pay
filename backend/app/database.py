from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    """Metadata for accounting models; schema changes are owned by Alembic."""


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_timeout=5,
        hide_parameters=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
