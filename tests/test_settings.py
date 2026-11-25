import pytest

from nimbus.agent.settings import agent_model, ollama_base_url, reasoning_effort, sampling_options


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("NIMBUS_AGENT_MODEL", "NIMBUS_REASONING_EFFORT", "NIMBUS_SEED", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def default_model_is_gemma():
    assert agent_model() == "gemma4:12b"


def test_explicit_model_wins(monkeypatch):
    monkeypatch.setenv("NIMBUS_AGENT_MODEL", "gemma4:26b")
    assert agent_model() == "gemma4:26b"


def test_blank_model_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NIMBUS_AGENT_MODEL", "")
    assert agent_model() == "gemma4:12b"


def test_reasoning_effort_defaults_medium(monkeypatch):
    assert reasoning_effort() == "medium"
    monkeypatch.setenv("NIMBUS_REASONING_EFFORT", "none")
    assert reasoning_effort() == "none"


def test_ollama_runs_locally_by_default():
    assert ollama_base_url() == "http://localhost:11434/v1"


def test_seed_is_integer(monkeypatch):
    monkeypatch.setenv("NIMBUS_SEED", "7")
    seed = sampling_options()["seed"]
    assert seed == 7
    assert isinstance(seed, int)
