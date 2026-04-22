import case_api.db as db


def test_public_database_url_masks_password(monkeypatch):
    monkeypatch.setattr(db, "_active_database_url", "postgresql+asyncpg://fraud:secret@db.internal:5432/fraud_cases")
    assert db.public_database_url() == "postgresql+asyncpg://fraud:***@db.internal:5432/fraud_cases"


def test_public_database_url_keeps_sqlite(monkeypatch):
    sqlite_url = "sqlite+aiosqlite:///tmp/case-api.db"
    monkeypatch.setattr(db, "_active_database_url", sqlite_url)
    assert db.public_database_url() == sqlite_url
