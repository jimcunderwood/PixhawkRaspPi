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

    def __init__(self, log_file: str):
        self.log_file = log_file
        self._lock = Lock()
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

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

        with self._lock:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(event, separators=(",", ":")) + "\n")

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
                with open(self.log_file, "r") as f:
                    lines = f.readlines()
        except FileNotFoundError:
            return []

        events = []
        for line in reversed(lines):
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
