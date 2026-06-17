"""
File-backed command audit logging.
"""

import json
import os
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional


class AuditLogger:
    """Append-only JSONL audit log for API commands."""

    def __init__(self, log_file: str, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 5):
        self.log_file = log_file
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = Lock()
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

    def _rotated_path(self, index: int) -> str:
        return f"{self.log_file}.{index}"

    def _existing_log_files(self) -> List[str]:
        files = [self.log_file]
        for index in range(1, self.backup_count + 1):
            rotated = self._rotated_path(index)
            if os.path.exists(rotated):
                files.append(rotated)
        return files

    def _rotate_if_needed(self, incoming_size: int):
        if self.max_bytes <= 0 or self.backup_count <= 0:
            return

        current_size = os.path.getsize(self.log_file) if os.path.exists(self.log_file) else 0
        if current_size + incoming_size <= self.max_bytes:
            return

        oldest = self._rotated_path(self.backup_count)
        if os.path.exists(oldest):
            os.remove(oldest)

        for index in range(self.backup_count - 1, 0, -1):
            src = self._rotated_path(index)
            dst = self._rotated_path(index + 1)
            if os.path.exists(src):
                os.replace(src, dst)

        if os.path.exists(self.log_file):
            os.replace(self.log_file, self._rotated_path(1))

    def record(
        self,
        action: str,
        outcome: str,
        parameters: Optional[Dict] = None,
        details: Optional[Dict] = None,
    ) -> Dict:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "outcome": outcome,
            "parameters": parameters or {},
            "details": details or {},
        }
        serialized = json.dumps(event, separators=(",", ":")) + "\n"

        with self._lock:
            self._rotate_if_needed(len(serialized))
            with open(self.log_file, "a") as f:
                f.write(serialized)

        return event

    def recent(
        self,
        limit: int = 100,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> List[Dict]:
        if limit < 1:
            return []

        try:
            with self._lock:
                lines = []
                for path in self._existing_log_files():
                    if not os.path.exists(path):
                        continue
                    with open(path, "r") as f:
                        lines.extend(reversed(f.readlines()))
        except FileNotFoundError:
            return []

        events = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if action and event.get("action") != action:
                continue
            if outcome and event.get("outcome") != outcome:
                continue

            events.append(event)
            if len(events) >= limit:
                break

        return events
