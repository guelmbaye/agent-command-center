"""No implicit state transition (Doc 04 §4, Doc 07 §27)."""
from __future__ import annotations

import pytest

from domain.enums import AgentStatus, MissionStatus, TaskStatus
from domain.errors import InvalidState
from domain.state_machine import (
    CRITICAL_TRANSITIONS,
    assert_agent_transition,
    assert_task_transition,
    assert_transition,
    can_transition,
)

S = MissionStatus


@pytest.mark.parametrize("current,target", CRITICAL_TRANSITIONS)
def test_critical_transitions_are_allowed(current, target):
    assert can_transition(current, target)


@pytest.mark.parametrize("current,target", [
    (S.COMPLETED, S.EXECUTING),
    (S.FAILED, S.EXECUTING),
    (S.ABORTED, S.RECOVERING),
    (S.CREATED, S.COMPLETED),
    (S.CREATED, S.RECOVERING),
    (S.AT_RISK, S.COMPLETED),
])
def test_forbidden_transitions_raise(current, target):
    with pytest.raises(InvalidState):
        assert_transition(current, target, "MIS-1")


def test_terminal_states_have_no_exit():
    for status in (S.COMPLETED, S.FAILED, S.ABORTED):
        assert status.is_terminal
        for target in S:
            assert not can_transition(status, target)


def test_completed_task_cannot_reopen():
    with pytest.raises(InvalidState):
        assert_task_transition(TaskStatus.COMPLETED, TaskStatus.RUNNING, "TASK-1")


def test_failed_agent_cannot_execute_silently():
    """Doc 02 §8: FAILED -> BUSY is forbidden; it must go through RECOVERING."""
    with pytest.raises(InvalidState):
        assert_agent_transition(AgentStatus.FAILED, AgentStatus.BUSY, "supply-agent")
    assert_agent_transition(AgentStatus.FAILED, AgentStatus.RECOVERING, "supply-agent")


def test_revoked_agent_is_final():
    for target in AgentStatus:
        with pytest.raises(InvalidState):
            assert_agent_transition(AgentStatus.REVOKED, target, "x")
