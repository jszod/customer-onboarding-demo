from datetime import timedelta
import pytest
from python import config


def test_defaults_match_spec_section_17(monkeypatch):
    for var in ("TASK_QUEUE", "MODEL", "MAX_ATTEMPTS", "MAX_ITERATIONS",
                "SLA_REMIND", "SLA_ESCALATE", "CLIENT_ID_SLA", "CORE_SLOW_MS",
                "FIXTURE_MODE", "PAYLOAD_CODEC"):
        monkeypatch.delenv(var, raising=False)
    s = config.settings()
    assert s.task_queue == "customer-onboarding"
    assert s.model == "claude-sonnet-5"
    assert s.max_attempts == 3
    assert s.max_iterations == 8
    assert s.sla_remind == timedelta(days=3)
    assert s.sla_escalate == timedelta(days=7)
    assert s.client_id_sla == timedelta(days=1)
    assert s.core_slow_ms == 10000
    assert s.fixture_mode is False
    assert s.payload_codec == "off"


def test_duration_env_accepts_short_form(monkeypatch):
    monkeypatch.setenv("SLA_REMIND", "30s")
    monkeypatch.setenv("SLA_ESCALATE", "60s")
    assert config.settings().sla_remind == timedelta(seconds=30)
    assert config.settings().sla_escalate == timedelta(seconds=60)


def test_data_converter_is_pydantic_aware():
    from temporalio.contrib.pydantic import pydantic_data_converter
    assert config.build_data_converter() is pydantic_data_converter


def test_payload_codec_on_is_rejected_until_implemented(monkeypatch):
    monkeypatch.setenv("PAYLOAD_CODEC", "on")
    with pytest.raises(NotImplementedError, match="§18"):
        config.build_data_converter()
