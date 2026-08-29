"""Checkpoints must tell what actually happened.

Usage regression: on a nominal mission **with no failure at all**, the
checkpoint list showed "Recovery plan selected" after merely preparing a
purchase. The mapping had been copied from the blueprint example, written for
the hero scenario, and never revisited for the nominal path.

A false label in the audit trail is as harmful as an invented event: the
operator reconstructs the mission from this list.
"""
from __future__ import annotations

import pytest

from domain.enums import MissionStatus


async def _settle(container, mission_id: str):
    await container.events.drain(timeout=60)
    return await container.store.get_mission(mission_id)


async def _labels(container, mission_id: str) -> list[str]:
    return [c.label for c in await container.checkpoints.list(mission_id)]


async def test_nominal_mission_never_mentions_recovery(container):
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    final = await _settle(container, mission.mission_id)
    assert final.status is MissionStatus.COMPLETED

    labels = await _labels(container, mission.mission_id)
    assert labels == [
        "Mission planned",
        "Supply analysis complete",
        "Risk assessment complete",
        "Purchase plan prepared",
        "Purchase executed",
        "Mission completed",
    ]
    assert not any("recovery" in label.lower() for label in labels), (
        "no failure occurred: mentioning recovery would be false"
    )


async def test_threshold_crossing_names_the_approval(container):
    mission = await container.engine.create_mission(
        "Seuil", context_overrides={"required_units": 1301})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    labels = await _labels(container, mission.mission_id)
    assert "Purchase awaiting approval" in labels
    assert not any("recovery" in label.lower() for label in labels)

    pending = await container.approvals.list(mission.mission_id, "PENDING")
    await container.approvals.decide(pending[0].approval_id, True, "operator")
    await _settle(container, mission.mission_id)

    labels = await _labels(container, mission.mission_id)
    assert "Human approval received" in labels
    assert "Purchase executed" in labels


async def test_recovery_path_does_mention_recovery(container, enterprise):
    """The guard must not erase genuine recovery checkpoints."""
    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    labels = await _labels(container, mission.mission_id)
    assert "Supplier failure detected" in labels
    assert "Recovery plan selected" in labels


async def test_every_checkpoint_stage_has_a_readable_label(container, enterprise):
    """A stage without a label would display its raw technical key."""
    from apps.api.services.checkpoint_service import CP_LABELS

    enterprise.suppliers["SUP-A"].failing = True
    mission = await container.engine.create_mission("Protect production schedule")
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    for checkpoint in await container.checkpoints.list(mission.mission_id):
        assert checkpoint.current_stage in CP_LABELS, (
            f"étape « {checkpoint.current_stage} » sans libellé lisible"
        )
        assert checkpoint.label != checkpoint.current_stage


@pytest.mark.parametrize("units,expected_absent", [
    (1200, "recovery"),   # mission nominale
    (1301, "recovery"),   # seuil franchi, toujours aucun échec
])
async def test_no_recovery_wording_without_a_failure(container, units, expected_absent):
    mission = await container.engine.create_mission(
        "X", context_overrides={"required_units": units})
    await container.engine.start(mission.mission_id)
    await _settle(container, mission.mission_id)

    recoveries = await container.store.list_recoveries(mission.mission_id)
    assert not recoveries, "aucune recovery ne doit avoir eu lieu"

    labels = await _labels(container, mission.mission_id)
    assert not any(expected_absent in label.lower() for label in labels)
