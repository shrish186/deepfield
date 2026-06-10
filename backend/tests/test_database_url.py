"""normalise_db_url rewrites sync Postgres URLs to the asyncpg driver and leaves
everything else (already-async, sqlite) untouched."""
from db.database import normalise_db_url


def test_postgresql_rewritten_to_asyncpg():
    assert (
        normalise_db_url("postgresql://user:pw@host:5432/db")
        == "postgresql+asyncpg://user:pw@host:5432/db"
    )


def test_heroku_postgres_scheme_rewritten():
    assert (
        normalise_db_url("postgres://user:pw@host:5432/db")
        == "postgresql+asyncpg://user:pw@host:5432/db"
    )


def test_already_asyncpg_passes_through():
    url = "postgresql+asyncpg://user:pw@host:5432/db"
    assert normalise_db_url(url) == url


def test_sqlite_passes_through():
    url = "sqlite+aiosqlite:///:memory:"
    assert normalise_db_url(url) == url


def test_only_first_occurrence_rewritten():
    # The scheme appears once; a password containing the literal text must not
    # be mangled by a global replace.
    url = "postgresql://u:postgresql@host/db"
    assert normalise_db_url(url) == "postgresql+asyncpg://u:postgresql@host/db"
