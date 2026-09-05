import datetime
import app.db as db


def test_default_anchor_is_the_data_not_the_clock():
    """This dataset ends 2026-06-30. Wall-clock 'this month' matches zero rows,
    and the assistant reports 'no transactions found' -- confidently wrong."""
    assert db.ANCHOR_MODE == "data"
    assert db.anchor_date() == db.data_max_date()


def test_status_reports_a_healthy_anchor():
    s = db.anchor_status()
    assert s["mode"] == "data" and s["stale"] is False and s["warning"] is None


def test_wall_clock_against_stale_data_is_flagged(monkeypatch):
    monkeypatch.setattr(db, "ANCHOR_MODE", "wall_clock")
    db.anchor_date.cache_clear()
    try:
        s = db.anchor_status()
        assert s["mode"] == "wall_clock"
        if datetime.date.today() > db.data_max_date():
            assert s["stale"] and "match no transactions" in s["warning"]
    finally:
        db.anchor_date.cache_clear()
