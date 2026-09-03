import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "tenants", "users", "departments", "contractors",
    "complaints", "complaint_media",
    "work_orders", "escalations", "notifications", "daily_briefings",
    "agent_runs", "agent_steps", "retrieved_chunks", "documents", "document_chunks",
    "eval_runs", "eval_results",
}


def test_migration_creates_every_table(tmp_path):
    db_file = tmp_path / "migrated.db"
    # sys.executable (not a bare "python") so the subprocess is guaranteed to
    # use the same interpreter running pytest -- and therefore the same venv
    # that has alembic/sqlalchemy installed -- regardless of what "python"
    # happens to resolve to on PATH.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db_file}"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(f"sqlite:///{db_file}")
    actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()

    missing = EXPECTED_TABLES - actual
    assert not missing, f"migration did not create: {sorted(missing)}"


def test_models_have_not_drifted_from_the_migration(tmp_path):
    """Guards the gap between conftest's create_all and the app's migrations."""
    db_file = tmp_path / "drift.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file}"}
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )
    assert check.returncode == 0, (
        f"models have drifted from the migration; run "
        f"`alembic revision --autogenerate`:\n{check.stdout}{check.stderr}"
    )
