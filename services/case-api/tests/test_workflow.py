"""Unit tests for workflow engine."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from case_api.workflow import (
    WorkflowContext,
    _evaluate_condition,
    _execute_action,
    compute_sla_deadline,
    evaluate_workflows,
    get_workflows,
    is_sla_breached,
    load_workflows,
)


class TestConditions:
    def _ctx(self, case=None, decision=None):
        return WorkflowContext(trigger="test", case=case or {}, decision=decision)

    def test_eq_match(self):
        ctx = self._ctx(case={"priority": "high"})
        assert _evaluate_condition(ctx, {"field": "priority", "op": "eq", "value": "high"}) is True

    def test_eq_miss(self):
        ctx = self._ctx(case={"priority": "low"})
        assert _evaluate_condition(ctx, {"field": "priority", "op": "eq", "value": "high"}) is False

    def test_neq(self):
        ctx = self._ctx(case={"status": "open"})
        assert _evaluate_condition(ctx, {"field": "status", "op": "neq", "value": "closed"}) is True

    def test_gte(self):
        ctx = self._ctx(decision={"score": 95})
        assert _evaluate_condition(ctx, {"field": "score", "op": "gte", "value": 90}) is True

    def test_contains_list(self):
        ctx = self._ctx(decision={"tags": ["sdk:bot", "sdk:vpn"]})
        assert (
            _evaluate_condition(ctx, {"field": "tags", "op": "contains", "value": "sdk:bot"})
            is True
        )

    def test_has_tag(self):
        ctx = self._ctx(case={"labels": ["high-risk"]})
        assert (
            _evaluate_condition(ctx, {"field": "", "op": "has_tag", "value": "high-risk"}) is True
        )


class TestActions:
    @pytest.mark.asyncio
    async def test_assign_team(self):
        ctx = WorkflowContext("test", {})
        await _execute_action(ctx, {"type": "assign_team", "team": "fraud-team"})
        assert ctx.mutations["assigned_team"] == "fraud-team"

    @pytest.mark.asyncio
    async def test_set_priority(self):
        ctx = WorkflowContext("test", {})
        await _execute_action(ctx, {"type": "set_priority", "priority": "critical"})
        assert ctx.mutations["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_escalate(self):
        ctx = WorkflowContext("test", {})
        await _execute_action(ctx, {"type": "escalate"})
        assert ctx.mutations["status"] == "escalated"
        assert ctx.mutations["priority"] == "critical"

    @pytest.mark.asyncio
    async def test_add_label(self):
        ctx = WorkflowContext("test", {"labels": ["existing"]})
        await _execute_action(ctx, {"type": "add_label", "labels": ["new", "other"]})
        assert "new" in ctx.mutations["labels"]
        assert "existing" in ctx.mutations["labels"]

    @pytest.mark.asyncio
    async def test_add_comment(self):
        ctx = WorkflowContext("test", {})
        await _execute_action(ctx, {"type": "add_comment", "message": "Auto-routed"})
        assert ctx.mutations["_comments"][0]["body"] == "Auto-routed"

    @pytest.mark.asyncio
    async def test_webhook(self):
        mock_http = AsyncMock()
        mock_http.post = AsyncMock()
        ctx = WorkflowContext("test", {"id": "c1"})
        await _execute_action(
            ctx, {"type": "send_webhook", "url": "https://example.com/hook"}, http=mock_http
        )
        mock_http.post.assert_called_once()
        assert ctx.actions_executed[0]["status"] == "sent"


class TestEvaluateWorkflows:
    @pytest.mark.asyncio
    async def test_full_workflow(self):
        wf = {
            "name": "test",
            "enabled": True,
            "triggers": ["case_created"],
            "conditions": [{"field": "priority", "op": "eq", "value": "high"}],
            "actions": [
                {"type": "assign_team", "team": "vip-team"},
                {"type": "add_label", "labels": ["vip"]},
            ],
        }
        import case_api.workflow as mod

        mod._workflows = [wf]

        ctx = await evaluate_workflows("case_created", {"priority": "high", "labels": []})
        assert ctx.mutations["assigned_team"] == "vip-team"
        assert "vip" in ctx.mutations["labels"]

    @pytest.mark.asyncio
    async def test_no_match(self):
        wf = {
            "name": "test",
            "enabled": True,
            "triggers": ["case_created"],
            "conditions": [{"field": "priority", "op": "eq", "value": "critical"}],
            "actions": [{"type": "escalate"}],
        }
        import case_api.workflow as mod

        mod._workflows = [wf]

        ctx = await evaluate_workflows("case_created", {"priority": "low"})
        assert ctx.mutations == {}

    @pytest.mark.asyncio
    async def test_wrong_trigger(self):
        wf = {
            "name": "test",
            "enabled": True,
            "triggers": ["decision_deny"],
            "conditions": [],
            "actions": [{"type": "escalate"}],
        }
        import case_api.workflow as mod

        mod._workflows = [wf]

        ctx = await evaluate_workflows("case_created", {})
        assert ctx.mutations == {}


class TestLoadWorkflows:
    def test_load_from_dir(self):
        wf = {
            "name": "test",
            "enabled": True,
            "triggers": ["case_created"],
            "conditions": [],
            "actions": [],
        }
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "test.json").write_text(json.dumps(wf))
            load_workflows(d)
            assert len(get_workflows()) == 1

    def test_skip_disabled(self):
        wf = {
            "name": "disabled",
            "enabled": False,
            "triggers": ["case_created"],
            "conditions": [],
            "actions": [],
        }
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "disabled.json").write_text(json.dumps(wf))
            load_workflows(d)
            assert len(get_workflows()) == 0

    def test_nonexistent_dir(self):
        load_workflows("/nonexistent/path")
        assert len(get_workflows()) == 0


class TestSLA:
    def test_sla_deadline_critical(self):
        now = datetime.now(UTC)
        deadline = compute_sla_deadline("critical", now)
        assert deadline == now + timedelta(hours=1)

    def test_sla_deadline_low(self):
        now = datetime.now(UTC)
        deadline = compute_sla_deadline("low", now)
        assert deadline == now + timedelta(hours=72)

    def test_breached(self):
        old = datetime.now(UTC) - timedelta(hours=25)
        assert is_sla_breached("medium", old) is True

    def test_not_breached(self):
        recent = datetime.now(UTC) - timedelta(minutes=5)
        assert is_sla_breached("medium", recent) is False

    def test_sla_deadline_override_hours(self):
        now = datetime.now(UTC)
        deadline = compute_sla_deadline("low", now, sla_hours_override=3)
        assert deadline == now + timedelta(hours=3)

    def test_breached_respects_override(self):
        old = datetime.now(UTC) - timedelta(hours=5)
        assert is_sla_breached("medium", old, sla_hours_override=2) is True
        assert is_sla_breached("medium", old, sla_hours_override=200) is False
