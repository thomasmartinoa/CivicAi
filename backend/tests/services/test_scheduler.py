"""What runs on a timer, and that one broken job cannot take the others down."""

import asyncio

import pytest

from app.config import settings
from app.services.scheduler import SLA_INTERVAL_MINUTES, build_scheduler


def _scheduler():
    return build_scheduler(session_factory=lambda: None)


def test_the_sla_job_is_registered_every_five_minutes():
    job = _scheduler().get_job("sla_monitor")
    assert job is not None
    assert job.trigger.interval.total_seconds() == SLA_INTERVAL_MINUTES * 60


def test_every_expected_job_is_registered():
    assert {j.id for j in _scheduler().get_jobs()} == {
        "sla_monitor", "cluster_detection", "daily_briefing", "cases_refresh",
    }


def test_cluster_detection_runs_hourly():
    assert _scheduler().get_job("cluster_detection").trigger.interval.total_seconds() == 3600


def test_the_briefing_runs_at_the_configured_hour(monkeypatch):
    monkeypatch.setattr(settings, "briefing_hour", 6)
    job = build_scheduler(session_factory=lambda: None).get_job("daily_briefing")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "6"
    assert fields["minute"] == "0"


def test_the_cases_refresh_runs_before_the_briefing(monkeypatch):
    """The briefing does not read the cases index, but assess_risk does, and a
    rebuild rewrites the index directory — so it happens off-peak and not while
    the morning's runs are starting."""
    monkeypatch.setattr(settings, "briefing_hour", 8)
    job = build_scheduler(session_factory=lambda: None).get_job("cases_refresh")
    hour = next(str(f) for f in job.trigger.fields if f.name == "hour")
    assert hour == "7"


@pytest.mark.parametrize("flag,job_id", [
    ("cluster_detection_enabled", "cluster_detection"),
    ("briefing_enabled", "daily_briefing"),
    ("cases_refresh_enabled", "cases_refresh"),
])
def test_a_disabled_job_is_not_registered(monkeypatch, flag, job_id):
    monkeypatch.setattr(settings, flag, False)
    assert build_scheduler(session_factory=lambda: None).get_job(job_id) is None


def test_the_sla_monitor_cannot_be_disabled_individually():
    """background_jobs_enabled is the master switch; the SLA monitor is the one
    job whose absence is silent — nobody notices a warning email that never
    came, which is how v1's briefing hid for a year."""
    assert _scheduler().get_job("sla_monitor") is not None


def test_jobs_do_not_stack_up_behind_a_slow_tick():
    for job in _scheduler().get_jobs():
        assert job.max_instances == 1, f"{job.id} may run concurrently with itself"
        assert job.coalesce is True, f"{job.id} would replay every missed run"


def test_a_failing_job_logs_and_does_not_raise(caplog):
    """A job that raises out of its own body kills nothing, but APScheduler only
    logs it once; every body here catches its own failure so the message names
    the job."""
    def boom():
        raise RuntimeError("database gone")

    scheduler = build_scheduler(session_factory=boom)
    job = scheduler.get_job("cluster_detection")
    with caplog.at_level("ERROR"):
        asyncio.run(job.func())
    assert "cluster" in caplog.text.lower()
    assert "database gone" in caplog.text
