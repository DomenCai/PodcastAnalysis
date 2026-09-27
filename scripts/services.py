"""Manage four local macOS launchd services (ASR, manager, reader, bot)."""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHISPER = ROOT.parent / "whisper"
AGENTS = Path.home() / "Library/LaunchAgents"
LABEL_PREFIX = "top.fullai.podcast"
SERVICES = ("asr", "manager", "public", "bot")
DATA = ROOT / "data"


def definition(name: str) -> dict:
    if name not in SERVICES:
        raise ValueError(f"未知服务：{name}")
    node = ""
    if name == "bot":
        node = subprocess.check_output(["node", "-p", "process.execPath"], text=True).strip()
    asr_python = WHISPER / ".venv/bin/python"
    podcast_python = ROOT / ".venv/bin/python"
    executable = Path(node) if name == "bot" else asr_python if name == "asr" else podcast_python
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"运行环境未安装：{executable}；请按 README 安装后重试")
    commands = {
        "asr": (WHISPER, f"ASR_HOST=127.0.0.1 ASR_PORT=18010 exec {shlex.quote(str(asr_python))} -m asr.app"),
        "manager": (ROOT, f"PODCAST_DATA_DIR={shlex.quote(str(DATA))} TRANSCRIPTION_API_URL=http://127.0.0.1:18010 HOST=127.0.0.1 PORT=18000 exec {shlex.quote(str(podcast_python))} -m server.app"),
        "public": (ROOT, f"PODCAST_DATA_DIR={shlex.quote(str(DATA))} PUBLIC_HOST=127.0.0.1 PUBLIC_PORT=8001 exec {shlex.quote(str(podcast_python))} -m server.public_app"),
        "bot": (ROOT / "bot", f"PODCAST_API_URL=http://127.0.0.1:18000 PODCAST_PUBLIC_URL=https://podcast.fullai.top exec {shlex.quote(node)} src/bot.js"),
    }
    cwd, command = commands[name]
    return {
        "Label": f"{LABEL_PREFIX}.{name}",
        "ProgramArguments": ["/bin/zsh", "-lc", f"cd {shlex.quote(str(cwd))} && {command}"],
        "RunAtLoad": True, "KeepAlive": True,
        "StandardOutPath": str(DATA / "logs" / f"{name}.log"),
        "StandardErrorPath": str(DATA / "logs" / f"{name}.error.log"),
    }


def plist(name: str) -> Path:
    return AGENTS / f"{LABEL_PREFIX}.{name}.plist"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], check=check, capture_output=True, text=True)


def loaded(name: str) -> bool:
    return run("print", f"gui/{os.getuid()}/{LABEL_PREFIX}.{name}", check=False).returncode == 0


def status(name: str) -> str:
    result = run("print", f"gui/{os.getuid()}/{LABEL_PREFIX}.{name}", check=False)
    if result.returncode != 0:
        return "未加载"
    return "运行中" if "state = running" in result.stdout else "已加载，未运行"


def main(action: str, names: list[str]) -> None:
    if action == "status":
        for name in names:
            print(f"{name}: {status(name)}")
        return
    if action in {"install", "start", "restart"}:
        # Resolve every requested runtime before stopping any working service.
        definitions = {
            name: definition(name) for name in names
            if action != "start" or not loaded(name)
        }
        if action == "install":
            for name in names:
                if plist(name).exists():
                    raise RuntimeError(f"配置已存在，未覆盖：{plist(name)}")
        DATA.joinpath("logs").mkdir(parents=True, exist_ok=True)
        AGENTS.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = plist(name)
            if action != "install" and loaded(name):
                if action == "restart":
                    run("bootout", f"gui/{os.getuid()}", str(target))
                else:
                    print(f"{name}: 已运行")
                    continue
            with target.open("wb") as file:
                plistlib.dump(definitions[name], file)
            if action != "install":
                run("bootstrap", f"gui/{os.getuid()}", str(target))
            print(f"{name}: {'已安装' if action == 'install' else '已启动'}")
    elif action == "stop":
        for name in reversed(names):
            if loaded(name):
                run("bootout", f"gui/{os.getuid()}", str(plist(name)))
                print(f"{name}: 已停止")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "start", "stop", "restart", "status"))
    parser.add_argument("services", nargs="*", choices=SERVICES)
    options = parser.parse_args()
    main(options.action, options.services or list(SERVICES))
