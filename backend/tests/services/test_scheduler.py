from app.services.scheduler import build_scheduler


def test_the_sla_job_is_registered_every_five_minutes():
    scheduler = build_scheduler(session_factory=lambda: None)
    job = scheduler.get_job("sla_monitor")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 300
