"""A minimal stdio MCP client: initialize, then page through tools/list.

Stdlib only. Reads the server's stdout on a background thread so a server that
hangs mid-handshake fails the deadline instead of blocking forever (the
research probe in ``tooling/probe.py`` could block on ``readline``).
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from typing import Any

# The client proposes the newest revision it speaks; servers answer with the one
# they support, and tools/list is unchanged across revisions.
PROTOCOL_VERSION = "2025-11-25"
MAX_PAGES = 100


class ProbeError(RuntimeError):
    pass


class _StdioSession:
    def __init__(self, cmd: list[str], env: dict[str, str] | None, timeout: float) -> None:
        self.deadline = time.monotonic() + timeout
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._next_id = 0

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        rid = self._next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError(f"timed out waiting for {method}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty:
                raise ProbeError(f"timed out waiting for {method}") from None
            if line is None:
                raise ProbeError(f"server exited before answering {method}: {self.stderr_tail()}")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers sometimes log to stdout; skip non-JSON lines
            if msg.get("id") != rid:
                continue  # notifications and server->client requests
            if "error" in msg:
                raise ProbeError(f"{method} failed: {msg['error']}")
            return msg.get("result") or {}

    def stderr_tail(self) -> str:
        try:
            self.proc.kill()
            assert self.proc.stderr is not None
            return self.proc.stderr.read()[-500:].strip()
        except (OSError, ValueError):
            return ""

    def close(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def fetch_tools(
    cmd: list[str], *, env: dict[str, str] | None = None, timeout: float = 60.0
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Launch ``cmd``, run the MCP handshake, return (tools, serverInfo+protocolVersion)."""
    session = _StdioSession(cmd, env, timeout)
    try:
        init = session.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-surface", "version": "1.1"},
            },
        )
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = session.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(page.get("tools") or [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        info = {**(init.get("serverInfo") or {}), "protocolVersion": init.get("protocolVersion")}
        return tools, info
    finally:
        session.close()
