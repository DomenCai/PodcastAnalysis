import pytest
from scripts import services


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    project = tmp_path / "projects with spaces" / "PodcastAnalysis"
    whisper = project.parent / "whisper"
    for root in (project, whisper):
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\n")
        python.chmod(0o700)
    monkeypatch.setattr(services, "ROOT", project)
    monkeypatch.setattr(services, "WHISPER", whisper)
    monkeypatch.setattr(services, "DATA", project / "data")
    monkeypatch.setattr(services, "AGENTS", tmp_path / "agents")
    return project, whisper


def test_python_services_use_standard_venv_without_requiring_node(deployment, monkeypatch):
    monkeypatch.setattr(services.subprocess, "check_output", lambda *a, **k: pytest.fail("Node should not be needed"))
    for name, root in (("asr", deployment[1]), ("manager", deployment[0]), ("public", deployment[0])):
        command = services.definition(name)["ProgramArguments"][-1]
        assert f"'{root}/.venv/bin/python'" in command
        assert ".venv-asr" not in command
    assert "ASR_PORT=18010" in services.definition("asr")["ProgramArguments"][-1]
    assert "PORT=18000" in services.definition("manager")["ProgramArguments"][-1]


def test_missing_runtime_is_detected_before_stopping_services(deployment, monkeypatch):
    (deployment[1] / ".venv/bin/python").unlink()
    monkeypatch.setattr(services, "loaded", lambda name: True)
    calls = []
    monkeypatch.setattr(services, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(RuntimeError, match="运行环境未安装"):
        services.main("restart", ["manager", "asr"])
    assert calls == []
    assert not services.AGENTS.exists()


def test_bot_uses_resolved_node_and_management_port(deployment, monkeypatch, tmp_path):
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n")
    node.chmod(0o700)
    monkeypatch.setattr(services.subprocess, "check_output", lambda *a, **k: str(node) + "\n")
    command = services.definition("bot")["ProgramArguments"][-1]
    assert "PODCAST_API_URL=http://127.0.0.1:18000" in command
    assert f"exec {node} src/bot.js" in command


def test_install_refuses_existing_configuration_before_writing_any(deployment, monkeypatch):
    services.AGENTS.mkdir()
    existing = services.plist("asr")
    existing.write_text("existing")
    with pytest.raises(RuntimeError, match="配置已存在"):
        services.main("install", ["manager", "asr"])
    assert existing.read_text() == "existing"
    assert not services.plist("manager").exists()
