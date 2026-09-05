"""Escalation tests (BACKLOG M6).

The planner hands off to the bigger "escalate" tier in two situations: the
small model fails to produce a valid spec twice in a row (case a), or
self-consistency sampling shows it could not agree with itself above
FINANCE_ESCALATE_THRESHOLD (case b). Either way `model_used`/`escalated` on
the PlanResult must say so, FINANCE_ESCALATE=0 must be a real kill switch, and
a genuine escalate call must land in app.llm.USAGE so efficiency_report()'s
escalation_rate is not structurally zero.
"""
import json

import app.llm as llm
import app.planner as planner_mod
from app.planner import (
    plan_detailed, plan_with_confidence, escalation_enabled, escalate_threshold,
)

GOOD = {"dataset": "payouts", "metric": "sum_amount", "group_by": []}
BAD = {"dataset": {"nested": "garbage"}, "group_by": {"also": "garbage"}}


def fake(payload):
    """Stand-in for the model: always returns `payload`, regardless of role."""
    def _f(role, system, user, temperature=None):
        return payload
    return _f


def role_dependent(*, planner=BAD, escalate=GOOD):
    """A different canned reply per role -- the small model struggles, the
    escalate tier does not."""
    def _f(role, system, user, temperature=None):
        return escalate if role == "escalate" else planner
    return _f


# --- helpers themselves -------------------------------------------------

def test_escalation_enabled_default_and_kill_switch(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    assert escalation_enabled()
    monkeypatch.setenv("FINANCE_ESCALATE", "0")
    assert not escalation_enabled()


def test_escalate_threshold_default_and_override(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE_THRESHOLD", raising=False)
    assert escalate_threshold() == 0.6
    monkeypatch.setenv("FINANCE_ESCALATE_THRESHOLD", "0.75")
    assert escalate_threshold() == 0.75


# --- case (a): parse/validation failure survives the repair round-trip ------

def test_escalates_on_parse_failure_after_repair(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    # A real, answerable question -- the point is that the SMALL MODEL's JSON
    # was garbage twice in a row, not that the question itself is unanswerable.
    r = plan_detailed("how much did I spend last month", chat_fn=role_dependent())
    assert r.escalated
    assert r.model_used == llm.MODELS["escalate"]
    assert not r.spec.unsupported_reason      # the bigger model recovered it
    assert r.confidence == "medium"           # needed the bigger tier -- not "high"


def test_still_refuses_honestly_if_escalation_also_fails(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    r = plan_detailed("something incoherent", chat_fn=fake(BAD))
    assert r.escalated                 # the attempt happened
    assert r.spec.unsupported_reason   # but it did not help -- refuse, never guess
    assert r.confidence == "low"


def test_finance_escalate_0_disables_the_repair_escalation(monkeypatch):
    monkeypatch.setenv("FINANCE_ESCALATE", "0")
    r = plan_detailed("something incoherent", chat_fn=role_dependent())
    assert not r.escalated
    assert r.spec.unsupported_reason
    assert r.model_used == llm.MODELS["planner"]


def test_no_escalation_needed_when_the_first_reply_is_fine():
    r = plan_detailed("where did I spend the most", chat_fn=fake(GOOD))
    assert not r.escalated
    assert r.model_used == llm.MODELS["planner"]
    assert r.confidence == "high"


# --- case (b): self-consistency below threshold -----------------------------

def _flaky(specs, escalate_reply=GOOD):
    """Returns a chat_fn that cycles through `specs` for role="planner" (so
    consecutive self-consistency samples disagree) and answers cleanly for
    role="escalate"."""
    calls = {"n": 0}
    def _f(role, system, user, temperature=None):
        if role == "escalate":
            return escalate_reply
        i = min(calls["n"], len(specs) - 1)
        calls["n"] += 1
        return specs[i]
    return _f


def test_escalates_on_low_self_consistency(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    monkeypatch.setitem(planner_mod.CFG, "confidence", {"samples": 3, "temperature": 0.7})
    disagreeing = [
        {"dataset": "payouts", "metric": "sum_amount", "group_by": []},
        {"dataset": "payouts", "metric": "count", "group_by": []},
        {"dataset": "payouts", "metric": "avg_amount", "group_by": []},
    ]
    r = plan_with_confidence("where did I spend the most", chat_fn=_flaky(disagreeing))
    assert r.escalated
    assert r.model_used == llm.MODELS["escalate"]


def test_high_confidence_does_not_escalate(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    monkeypatch.setitem(planner_mod.CFG, "confidence", {"samples": 3, "temperature": 0.7})
    r = plan_with_confidence("where did I spend the most", chat_fn=fake(GOOD))
    assert not r.escalated
    assert r.confidence == "high"


def test_finance_escalate_0_disables_confidence_escalation(monkeypatch):
    monkeypatch.setenv("FINANCE_ESCALATE", "0")
    monkeypatch.setitem(planner_mod.CFG, "confidence", {"samples": 3, "temperature": 0.7})
    disagreeing = [
        {"dataset": "payouts", "metric": "sum_amount", "group_by": []},
        {"dataset": "payouts", "metric": "count", "group_by": []},
        {"dataset": "payouts", "metric": "avg_amount", "group_by": []},
    ]
    r = plan_with_confidence("where did I spend the most", chat_fn=_flaky(disagreeing))
    assert not r.escalated
    assert r.confidence == "low"


# --- the real chat()/USAGE path: proves efficiency_report() is not structurally zero --

def test_usage_log_records_a_real_escalate_call_and_shows_in_efficiency_report(monkeypatch):
    monkeypatch.delenv("FINANCE_ESCALATE", raising=False)
    llm.USAGE.clear()

    def fake_chat(role, system, user, *, temperature=None, json_mode=False,
                  max_tokens=1500, schema=None):
        # Mirrors what the real chat() does for every call: log it, then answer.
        llm.USAGE.append({"role": role, "model": f"test-{role}", "tokens": 5})
        return json.dumps(GOOD) if role == "escalate" else json.dumps(BAD)

    monkeypatch.setattr(llm, "chat", fake_chat)
    r = plan_detailed("something incoherent")     # no chat_fn -- goes through chat_json/chat
    assert r.escalated

    report = llm.efficiency_report()
    assert report["escalations"] >= 1
    assert report["escalation_rate"] > 0
