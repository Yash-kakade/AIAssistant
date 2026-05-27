from sqlalchemy import inspect, text
from .database import engine


def migrate_schema() -> None:
    """Apply lightweight SQLite migrations for existing databases."""
    insp = inspect(engine)
    if not insp.has_table("employees"):
        return

    columns = {c["name"] for c in insp.get_columns("employees")}
    with engine.begin() as conn:
        if "salary" not in columns:
            conn.execute(text("ALTER TABLE employees ADD COLUMN salary REAL DEFAULT 65000.0"))
            conn.execute(text("UPDATE employees SET salary = 65000.0 WHERE salary IS NULL"))
