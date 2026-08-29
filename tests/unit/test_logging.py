"""A log line must never bring down a mission."""
from __future__ import annotations

import json
import logging

import pytest

from apps.api.core.logging import ACCJsonFormatter, configure_logging, get_logger


@pytest.mark.parametrize("field", ["message", "args", "name", "levelname", "module"])
def test_reserved_field_names_do_not_raise(field, caplog):
    """Services log arbitrary business fields."""
    logger = get_logger("acc.test")
    with caplog.at_level(logging.INFO):
        logger.info("event_published", extra={field: "valeur metier"})
    assert caplog.records
    assert getattr(caplog.records[0], f"ctx_{field}") == "valeur metier"


def test_business_fields_are_preserved(caplog):
    logger = get_logger("acc.test")
    with caplog.at_level(logging.INFO):
        logger.info("policy_decision", extra={"decision": "DENY", "rule_id": "R-1"})
    record = caplog.records[0]
    assert record.decision == "DENY"
    assert record.rule_id == "R-1"


def test_formatter_emits_valid_json():
    logger = logging.getLogger("acc.fmt")
    record = logger.makeRecord("acc.fmt", logging.INFO, __file__, 1,
                               "mission_created", (), None)
    record.mission_id = "MIS-1001"
    payload = json.loads(ACCJsonFormatter().format(record))
    assert payload["message"] == "mission_created"
    assert payload["mission_id"] == "MIS-1001"
    assert payload["level"] == "INFO"


def test_configure_logging_is_idempotent():
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(logging.getLogger().handlers) == 1
