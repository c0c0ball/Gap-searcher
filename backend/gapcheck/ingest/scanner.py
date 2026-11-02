"""업로드 검역. clamd INSTREAM 프로토콜을 직접 구현한다 (외부 라이브러리 없이)."""
from __future__ import annotations

import socket
import struct
from typing import Protocol


class Scanner(Protocol):
    def scan(self, data: bytes) -> tuple[str, str]:
        """(status, detail) — status ∈ clean | infected | error | not_scanned"""
        ...


class ClamdScanner:
    CHUNK = 64 * 1024

    def __init__(self, host: str, port: int, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> tuple[str, str]:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), self.CHUNK):
                    chunk = data[i:i + self.CHUNK]
                    s.sendall(struct.pack("!L", len(chunk)) + chunk)
                s.sendall(struct.pack("!L", 0))
                reply = s.recv(4096).strip(b"\0").decode(errors="replace")
        except OSError as e:
            return "error", f"clamd 연결 실패: {e}"
        # 예: "stream: OK" / "stream: Eicar-Test-Signature FOUND"
        if reply.endswith("OK"):
            return "clean", reply
        if reply.endswith("FOUND"):
            return "infected", reply
        return "error", reply


class NoScanner:
    """로컬 CLI·테스트용. 검사하지 않았다는 사실을 그대로 기록한다 (clean으로 위장하지 않음)."""

    def scan(self, data: bytes) -> tuple[str, str]:
        return "not_scanned", "스캐너 미사용 (로컬 실행)"
