"""A minimal MCP stdio client: JSON-RPC 2.0 over a subprocess's stdin/stdout.

Enough to initialize a server, list its tools and call one. Deliberately
small — NEXUS talks to two or three MCP servers, not to an ecosystem, and
a full SDK would be a dependency for about eighty lines of protocol.
"""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

PROTOCOL_VERSION = "2026-11-05"


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self, command: list[str], cwd: str | None = None,
                 timeout: float = 120.0, env: dict | None = None):
        self.command = command
        self.cwd = cwd
        self.timeout = timeout
        self.env = env
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._stderr: list[str] = []

    # ---------- lifecycle ----------

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> dict:
        self.proc = subprocess.Popen(
            self.command, cwd=self.cwd, env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        # Drain stderr in the background; a blocked stderr pipe deadlocks the server.
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "nexus", "version": "0.2.0"},
        })
        self.notify("notifications/initialized")
        return result

    def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-200]  # keep the tail, not the history

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        finally:
            self.proc = None

    # ---------- transport ----------

    def _send(self, payload: dict) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("server is not running")
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        req_id = self._id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})

        timer = threading.Timer(self.timeout, lambda: self.proc and self.proc.kill())
        timer.start()
        try:
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # servers sometimes print banners on stdout
                if msg.get("id") != req_id:
                    continue  # a notification or another response
                if "error" in msg:
                    raise MCPError(f"{method}: {msg['error']}")
                return msg.get("result")
        finally:
            timer.cancel()
        tail = "\n".join(self._stderr[-5:])
        raise MCPError(f"{method}: server closed the connection{chr(10) + tail if tail else ''}")

    # ---------- convenience ----------

    def tools(self) -> list[dict]:
        return (self.request("tools/list") or {}).get("tools", [])

    def call(self, name: str, arguments: dict) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            raise MCPError(f"{name}: {result.get('content')}")
        return result

    @staticmethod
    def text_of(result: Any) -> str:
        """MCP results are content blocks; most servers return one text block."""
        if not isinstance(result, dict):
            return str(result)
        parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return "\n".join(p for p in parts if p)
