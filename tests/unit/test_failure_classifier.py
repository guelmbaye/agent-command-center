"""Classification d'echecs et regles de retry (Doc 05 §17, Doc 02 §15)."""
from __future__ import annotations

import pytest

from apps.api.services.failure_classifier import classify_exception, classify_http, retry_allowed
from domain.enums import FailureClass


@pytest.mark.parametrize("code,expected", [
    (503, FailureClass.DEPENDENCY),   # panne fournisseur du scenario hero
    (502, FailureClass.DEPENDENCY),
    (504, FailureClass.TIMEOUT),
    (429, FailureClass.TRANSIENT),
    (403, FailureClass.AUTHORIZATION),
    (404, FailureClass.PERMANENT),
])
def test_http_classification(code, expected):
    assert classify_http(code) is expected


def test_exception_classification():
    assert classify_exception(TimeoutError("deadline")) is FailureClass.TIMEOUT
    assert classify_exception(ConnectionError("connection refused")) is FailureClass.DEPENDENCY
    assert classify_exception(PermissionError("forbidden")) is FailureClass.AUTHORIZATION


def test_retry_never_allowed_on_security_failures():
    assert not retry_allowed(FailureClass.SECURITY, attempt=1)
    assert not retry_allowed(FailureClass.AUTHORIZATION, attempt=1)


def test_retry_only_for_transient_within_budget():
    assert retry_allowed(FailureClass.TRANSIENT, attempt=1)
    assert retry_allowed(FailureClass.TIMEOUT, attempt=2)
    assert not retry_allowed(FailureClass.TRANSIENT, attempt=3)
    assert not retry_allowed(FailureClass.DEPENDENCY, attempt=1)
