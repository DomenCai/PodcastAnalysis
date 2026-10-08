"""Invoke one analysis CLI and reduce its private output to safe diagnostics."""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AnalysisError(RuntimeError):
    def __init__(self, message: str, *, category: str = "validation", retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class AnalysisConfig:
    backend: str
    model: str
    thinking: str | None
    timeout: float
    attempts: int

    @classmethod
    def from_env(cls) -> AnalysisConfig:
        backend = os.getenv("PODCAST_ANALYSIS_BACKEND", "pi").strip().lower()
        if backend not in {"pi", "agy"}:
            raise AnalysisError("PODCAST_ANALYSIS_BACKEND 必须是 pi 或 agy", category="config")
        model = "kimi/k3" if backend == "pi" else os.getenv("PODCAST_AGY_MODEL", "gemini-3.1-pro-high").strip()
        if backend == "agy" and not model.startswith("gemini-"):
            raise AnalysisError("PODCAST_AGY_MODEL 必须选择 Gemini 模型", category="config")
        try:
            timeout = float(os.getenv("PODCAST_ANALYSIS_TIMEOUT_SECONDS", "1200"))
            attempts = int(os.getenv("PODCAST_ANALYSIS_ATTEMPTS", "2"))
        except ValueError as exc:
            raise AnalysisError("分析时限必须是数字，尝试次数必须是整数", category="config") from exc
        if not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise AnalysisError("PODCAST_ANALYSIS_TIMEOUT_SECONDS 必须在 0 到 86400 秒之间", category="config")
        if not 1 <= attempts <= 5:
            raise AnalysisError("PODCAST_ANALYSIS_ATTEMPTS 必须在 1 到 5 之间", category="config")
        return cls(backend, model, "high" if backend == "pi" else None, timeout, attempts)


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The leader may exit before grandchildren; always clean up the original group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _transient_category(text: str) -> str | None:
    if re.search(r"\bEOF\b|tls:|TLS handshake timeout|connection (?:reset|refused|closed)|"
                 r"broken pipe|network is unreachable|ENOTFOUND|ECONNRESET|ETIMEDOUT|fetch failed|"
                 r"socket hang up|temporary failure in name resolution", text, re.I):
        return "network"
    if re.search(r"rate.?limit|too many requests|(?:status|HTTP|code)\D{0,10}429\b", text, re.I):
        return "rate_limit"
    if re.search(r"overloaded|service unavailable|bad gateway|gateway timeout|"
                 r"(?:status|HTTP|code)\D{0,10}(?:500|502|503|504)\b|500 internal server error", text, re.I):
        return "upstream"
    return None


def _failure(text: str, *, timed_out: bool, exit_code: int | None) -> AnalysisError:
    if re.search(r"auto-denied|command[\" ]+permission|permission denied|tool.*denied", text, re.I):
        return AnalysisError("模型工具权限被拒绝", category="permission")
    if re.search(r"insufficient.?quota|quota exceeded|credit.*exhaust|余额不足", text, re.I):
        return AnalysisError("模型额度不足", category="quota")
    if re.search(r"not eligible|invalid.api.key|unauthorized|authentication failed|"
                 r"(?:status|HTTP|code)\D{0,10}(?:401|403)\b", text, re.I):
        return AnalysisError("模型账号或鉴权不可用", category="auth")
    # "Eligibility check failed: EOF" is a network error; an explicit account
    # rejection above must not be masked by an unrelated startup network failure.
    transient = _transient_category(text)
    if transient:
        label = {"network": "网络连接异常", "rate_limit": "请求限流", "upstream": "上游服务暂时异常"}[transient]
        return AnalysisError(label, category=transient, retryable=True)
    if timed_out or re.search(r"timed out|timeout|deadline exceeded", text, re.I):
        return AnalysisError("模型调用超时", category="timeout")
    if exit_code:
        return AnalysisError(f"模型进程失败（退出码 {exit_code}）", category="process_exit")
    return AnalysisError("模型未返回完整成功结果", category="invalid_response")


def _error_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:16000]
    if isinstance(value, dict):
        return " ".join(_error_text(value.get(key)) for key in ("message", "error", "code", "status"))
    return ""


def _usage(value: Any) -> dict:
    allowed = {"input", "output", "cacheRead", "cacheWrite", "totalTokens", "input_tokens",
               "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens"}
    return {k: v for k, v in value.items() if k in allowed and type(v) in (int, float) and math.isfinite(v)} if isinstance(value, dict) else {}


def _parse_output(stream, backend: str) -> dict:
    stream.seek(0)
    result: dict = {}
    final: dict = {}
    settled = False
    errors: list[str] = []
    plain_errors: list[str] = []
    tool_errors = 0
    retries = 0
    usage: dict[str, int | float] = {}
    for raw in stream:
        line = raw.decode("utf-8", errors="replace").strip()
        try:
            event = json.loads(line)
        except ValueError:
            # Only CLI diagnostic-looking lines, never JSON text/thinking/tool content.
            if re.match(r"(?i)^(?:error\b|fatal\b|eligibility check failed\b|jetski:|.*auto-denied)", line):
                plain_errors.append(line[:16000])
            continue
        if not isinstance(event, dict):
            continue
        if backend == "agy":
            if "status" in event:
                result = event
            continue
        kind = event.get("type")
        if kind == "agent_start":
            settled = False
        elif kind == "agent_settled":
            settled = True
        elif kind == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                final = message
                for key, value in _usage(message.get("usage")).items():
                    usage[key] = usage.get(key, 0) + value
        elif kind == "tool_execution_end" and event.get("isError"):
            tool_errors += 1
        elif kind == "auto_retry_start":
            retries += 1
    if backend == "agy":
        status = result.get("status")
        known = {"SUCCESS", "ERROR", "FAILED", "CANCELLED", "TIMEOUT"}
        errors.append(_error_text(result.get("error")))
        errors.append(_error_text(result.get("errorMessage")))
        return {"success": status == "SUCCESS" and not result.get("denied_actions"),
                "status": status if isinstance(status, str) and status in known else "UNKNOWN",
                "denied": bool(result.get("denied_actions")), "usage": _usage(result.get("usage")),
                "errors": "\n".join(errors + plain_errors), "tool_errors": 0, "internal_retries": 0}
    stop = final.get("stopReason")
    errors.append(_error_text(final.get("errorMessage")))
    return {"success": settled and stop == "stop", "status": "SETTLED" if settled else "INCOMPLETE",
            "stop_reason": stop if isinstance(stop, str) and stop in {"stop", "length", "toolUse", "error", "aborted"} else "UNKNOWN",
            "model_matches": final.get("provider") == "kimi" and final.get("model") == "k3",
            "usage": usage, "errors": "\n".join(errors + plain_errors),
            "denied": False, "tool_errors": tool_errors, "internal_retries": retries}


def _agy_errors(path: Path) -> str:
    if not path.is_file():
        return ""
    # Bind the file to this invocation via --log-file. Ignore telemetry/background
    # errors, which can occur even when the model request succeeds.
    errors = []
    with path.open(errors="replace") as stream:
        for line in stream:
            if re.search(r"Run: attempt \d+ failed|Print mode:.*(?:failed|error)|"
                         r"failed to get model config|Validation failed", line):
                errors.append(line[:16000])
    return "\n".join(errors[-20:])


def invoke(work: Path, prompt: str, config: AnalysisConfig, diagnostic: dict,
           executable: str | Path | None = None) -> dict:
    executable = os.fspath(executable or config.backend)
    skill = work / ".skills/podcast-to-article/SKILL.md"
    with tempfile.TemporaryDirectory(prefix="podcast-cli-") as logs:
        cli_log = Path(logs) / "cli.log"
        if config.backend == "pi":
            argv = [executable, "--offline", "--model", config.model, "--thinking", config.thinking,
                    "--mode", "json", "--print", "--no-session", "--no-extensions", "--no-skills",
                    "--skill", str(skill), "--no-prompt-templates", "--no-context-files", "--no-approve",
                    "--tools", "read,write,edit,grep,find,ls", "/skill:podcast-to-article " + prompt]
            wait_timeout = config.timeout
        else:
            argv = [executable, "--model", config.model, "-p", prompt, "--add-dir", str(work),
                    "--mode", "accept-edits", "--sandbox", "--output-format", "json",
                    "--print-timeout", f"{config.timeout:g}s", "--log-file", str(cli_log)]
            wait_timeout = config.timeout + 15
        with tempfile.TemporaryFile(mode="w+b") as output:
            try:
                process = subprocess.Popen(argv, cwd=work, stdin=subprocess.DEVNULL,
                                           stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                raise AnalysisError(f"无法启动 {config.backend}，请检查安装与 PATH", category="startup") from exc
            timed_out = False
            try:
                code = process.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_group(process)
                code = process.returncode
            diagnostic.update(exit_code=code, timed_out=timed_out)
            parsed = _parse_output(output, config.backend)
            timed_out = timed_out or parsed["status"] == "TIMEOUT"
            diagnostic.update(timed_out=timed_out,
                              **{k: v for k, v in parsed.items() if k not in {"errors", "success", "denied"}})
            if parsed["denied"]:
                raise AnalysisError("模型工具权限被拒绝", category="permission")
            if not timed_out and code == 0 and parsed["success"]:
                if config.backend == "pi" and not parsed["model_matches"]:
                    raise AnalysisError("pi 返回的模型与 kimi/k3 不一致", category="model_mismatch")
                return {"backend": config.backend, "model": config.model,
                        "thinking": config.thinking, "usage": parsed["usage"]}
            if parsed.get("stop_reason") == "length":
                raise AnalysisError("模型输出达到长度上限", category="output_limit")
            errors = parsed["errors"] + "\n" + (_agy_errors(cli_log) if config.backend == "agy" else "")
            failure = _failure(errors, timed_out=timed_out, exit_code=code)
            if failure.category == "timeout":
                diagnostic["timed_out"] = True
            raise failure
