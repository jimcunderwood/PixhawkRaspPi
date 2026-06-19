"""
Flight log synchronization and archive management.

Creates a post-flight bundle containing Pixhawk logs, companion logs, telemetry
snapshots, and spray records. Uploads can be enabled through an HTTP endpoint.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import config

logger = logging.getLogger(__name__)


class FlightLogSyncManager:
    """Automatic Pixhawk and companion log archive sync."""

    def __init__(self, connection_manager, payload_controller, telemetry_manager, storage_config):
        self.connection_manager = connection_manager
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.storage_config = storage_config
        self.base_directory = Path(storage_config.flight_log_directory)
        self.base_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._running_sync = False
        self._last_result: Dict = {"status": "idle", "updated_at": None}
        self._last_landing_at: Optional[float] = None
        self._last_armed_at: Optional[float] = None
        self._register_callbacks()

    def _register_callbacks(self):
        try:
            self.connection_manager.register_callback("armed", self._on_armed)
            self.connection_manager.register_callback("landing", self._on_landing)
            self.connection_manager.register_callback("disarmed", self._on_disarmed)
        except Exception as e:
            logger.warning("Unable to register flight log sync callbacks: %s", str(e))

    def _on_armed(self, *_args, **_kwargs):
        self._last_armed_at = time.time()

    def _on_landing(self, *_args, **_kwargs):
        self._last_landing_at = time.time()
        self._schedule_sync("landing")

    def _on_disarmed(self, *_args, **_kwargs):
        if self._last_armed_at is not None:
            self._schedule_sync("disarmed")

    def _schedule_sync(self, reason: str):
        with self._lock:
            if self._running_sync:
                return
            self._running_sync = True

        worker = threading.Thread(target=self._sync_worker, args=(reason,), daemon=True)
        worker.start()

    def _sync_worker(self, reason: str):
        try:
            time.sleep(max(0.0, float(self.storage_config.flight_log_sync_delay_seconds)))
            result = self.sync_now(reason=reason)
            self._last_result = result
        except Exception as e:
            logger.error("Flight log sync failed: %s", str(e))
            self._last_result = {
                "status": "failed",
                "reason": reason,
                "error": str(e),
                "updated_at": time.time(),
            }
        finally:
            with self._lock:
                self._running_sync = False

    def status(self) -> Dict:
        return {
            **self._last_result,
            "running": self._running_sync,
            "last_landing_at": self._last_landing_at,
            "last_armed_at": self._last_armed_at,
            "base_directory": str(self.base_directory),
        }

    def history(self, limit: int = 10) -> List[Dict]:
        if limit <= 0:
            return []

        records: List[Dict] = []
        for session_directory in sorted(
            (path for path in self.base_directory.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            for archive_path in sorted(
                (candidate for candidate in session_directory.rglob("*.zip") if candidate.is_file()),
                key=lambda candidate: candidate.stat().st_mtime,
                reverse=True,
            ):
                record = self._describe_archive(archive_path)
                if record:
                    records.append(record)
                if len(records) >= limit:
                    return records
        return records

    def replay(self, archive_path: str, upload: bool = False) -> Dict:
        candidate = Path(archive_path)
        if not candidate.is_absolute():
            candidate = self.base_directory / candidate

        if not candidate.exists() or candidate.suffix.lower() != ".zip":
            raise FileNotFoundError(f"Flight log archive not found: {archive_path}")

        manifest = self._describe_archive(candidate)
        if manifest is None:
            raise ValueError(f"Flight log archive is missing a manifest: {candidate}")

        upload_result = {"enabled": False}
        if upload:
            upload_result = self._upload_archive(candidate, candidate.with_name("manifest.json"))

        return {
            **manifest,
            "replayed_at": time.time(),
            "upload": upload_result,
        }

    def sync_now(self, reason: str = "manual") -> Dict:
        session_name = self._session_name()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle_dir = self.base_directory / session_name / timestamp
        pixhawk_dir = bundle_dir / "pixhawk"
        companion_dir = bundle_dir / "companion"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        pixhawk_dir.mkdir(parents=True, exist_ok=True)
        companion_dir.mkdir(parents=True, exist_ok=True)

        pixhawk_files = self._download_pixhawk_logs(pixhawk_dir)
        companion_files = self._collect_companion_artifacts(companion_dir)
        manifest = self._write_manifest(bundle_dir, session_name, reason, pixhawk_files, companion_files)
        archive_path = self._create_archive(bundle_dir, manifest)
        upload_result = self._upload_archive(archive_path, manifest)
        self._enforce_storage_budget()
        self._prune_session_archives(bundle_dir.parent)

        return {
            "status": "success",
            "reason": reason,
            "session": session_name,
            "bundle_directory": str(bundle_dir),
            "archive_path": str(archive_path),
            "pixhawk_files": [str(path) for path in pixhawk_files],
            "companion_files": [str(path) for path in companion_files],
            "upload": upload_result,
            "updated_at": time.time(),
        }

    def cleanup_all(self) -> Dict:
        removed = {
            "archives": 0,
            "bundle_directories": 0,
            "other_files": 0,
        }

        if not self.base_directory.exists():
            return {"removed": removed}

        for path in sorted(self.base_directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_file():
                    if path.suffix.lower() == ".zip":
                        removed["archives"] += 1
                    else:
                        removed["other_files"] += 1
                    path.unlink()
                elif path.is_dir() and path != self.base_directory:
                    shutil.rmtree(path, ignore_errors=False)
                    removed["bundle_directories"] += 1
            except OSError as e:
                logger.warning("Failed to remove flight log path %s: %s", path, str(e))

        return {"removed": removed}

    def download_archive(self, archive_path: Optional[str] = None) -> Path:
        if archive_path:
            candidate = Path(archive_path)
            if not candidate.is_absolute():
                candidate = self.base_directory / candidate
            if not candidate.is_file() or candidate.suffix.lower() != ".zip":
                matches = [path for path in self.base_directory.rglob(candidate.name) if path.is_file() and path.suffix.lower() == ".zip"]
                if len(matches) == 1:
                    candidate = matches[0]
                else:
                    raise FileNotFoundError(f"Flight log archive not found: {archive_path}")
            return candidate

        archives = self._list_archives()
        if not archives:
            raise FileNotFoundError("No flight log archives are available.")
        return archives[-1]

    def _session_name(self) -> str:
        active_session = getattr(self.payload_controller, "active_spray_session", None)
        if active_session:
            return str(active_session)

        current_state = self.telemetry_manager.get_current() or {}
        if current_state.get("mode"):
            return f"flight_{current_state['mode']}"

        return datetime.now(timezone.utc).strftime("flight_%Y%m%d")

    def _download_pixhawk_logs(self, target_directory: Path) -> List[Path]:
        vehicle = getattr(self.connection_manager, "vehicle", None)
        master = getattr(vehicle, "_master", None) if vehicle else None
        mav = getattr(master, "mav", None) if master else None
        if not vehicle or not master or not mav:
            logger.info("Pixhawk log download skipped because MAVLink is unavailable")
            return []

        try:
            target_system = getattr(master, "target_system", 1)
            target_component = getattr(master, "target_component", 1)
            mav.log_request_list_send(target_system, target_component, 0, 0xFFFF)
        except Exception as e:
            logger.warning("Unable to request Pixhawk log list: %s", str(e))
            return []

        entries = []
        deadline = time.time() + 10.0
        while time.time() < deadline and len(entries) < max(1, int(self.storage_config.flight_log_download_limit)):
            try:
                message = master.recv_match(type="LOG_ENTRY", blocking=True, timeout=1)
            except Exception:
                message = None
            if message is None:
                break
            entries.append(message)

        downloaded: List[Path] = []
        for entry in entries:
            log_id = getattr(entry, "id", None)
            size = int(getattr(entry, "size", 0) or 0)
            if log_id is None or size <= 0:
                continue
            file_name = f"pixhawk_{int(log_id):05d}.bin"
            buffer = bytearray()
            offset = 0
            try:
                while offset < size:
                    mav.log_request_data_send(target_system, target_component, int(log_id), offset, 90)
                    chunk = None
                    chunk_deadline = time.time() + 2.0
                    while time.time() < chunk_deadline:
                        try:
                            message = master.recv_match(type="LOG_DATA", blocking=True, timeout=1)
                        except Exception:
                            message = None
                        if message is None:
                            continue
                        if int(getattr(message, "id", -1)) != int(log_id):
                            continue
                        if int(getattr(message, "ofs", -1)) != offset:
                            continue
                        data = bytes(getattr(message, "data", b""))
                        count = int(getattr(message, "count", 0) or len(data))
                        chunk = data[:count]
                        break

                    if chunk is None:
                        break

                    buffer.extend(chunk)
                    offset += len(chunk)
                    if len(chunk) < 90:
                        break

                if buffer:
                    path = target_directory / file_name
                    path.write_bytes(buffer)
                    downloaded.append(path)
            except Exception as e:
                logger.warning("Failed to download Pixhawk log %s: %s", log_id, str(e))

        return downloaded

    def _collect_companion_artifacts(self, target_directory: Path) -> List[Path]:
        copied: List[Path] = []
        artifacts = [
            Path(config.api.audit_log_file),
            Path(config.storage.telemetry_database_file),
        ]
        for artifact in artifacts:
            if not artifact.exists():
                continue
            destination = target_directory / artifact.name
            try:
                shutil.copy2(artifact, destination)
                copied.append(destination)
            except OSError as e:
                logger.warning("Failed to copy artifact %s: %s", artifact, str(e))

        payload_records_dir = Path(getattr(self.payload_controller.config, "spray_application_record_directory", ""))
        if payload_records_dir.is_dir():
            destination = target_directory / "spray-application-records"
            try:
                shutil.copytree(payload_records_dir, destination, dirs_exist_ok=True)
                copied.append(destination)
            except OSError as e:
                logger.warning("Failed to copy application records %s: %s", payload_records_dir, str(e))

        telemetry_history = self.telemetry_manager.get_history()
        history_path = target_directory / "telemetry-history.json"
        try:
            history_path.write_text(json.dumps(telemetry_history, indent=2, sort_keys=True))
            copied.append(history_path)
        except OSError as e:
            logger.warning("Failed to write telemetry history snapshot: %s", str(e))

        return copied

    def _write_manifest(
        self,
        bundle_dir: Path,
        session_name: str,
        reason: str,
        pixhawk_files: List[Path],
        companion_files: List[Path],
    ) -> Path:
        manifest = {
            "session": session_name,
            "reason": reason,
            "created_at": time.time(),
            "created_at_iso": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "pixhawk_files": [str(path.relative_to(bundle_dir)) for path in pixhawk_files],
            "companion_files": [str(path.relative_to(bundle_dir)) for path in companion_files],
        }
        path = bundle_dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return path

    def _create_archive(self, bundle_dir: Path, manifest_path: Path) -> Path:
        archive_path = bundle_dir.with_suffix(".zip")
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in bundle_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle_dir.parent))
        return archive_path

    def _upload_archive(self, archive_path: Path, manifest_path: Path) -> Dict:
        if not self.storage_config.flight_log_cloud_upload_enabled:
            return {"enabled": False}
        if not self.storage_config.flight_log_cloud_upload_url:
            return {"enabled": True, "status": "skipped", "reason": "missing upload url"}

        payload = archive_path.read_bytes()
        request = urllib.request.Request(
            self.storage_config.flight_log_cloud_upload_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/zip",
                "X-Archive-Name": archive_path.name,
                "X-Manifest-Name": manifest_path.name,
            },
        )
        with urllib.request.urlopen(request, timeout=self.storage_config.flight_log_cloud_upload_timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            return {
                "enabled": True,
                "status": "uploaded",
                "http_status": getattr(response, "status", 200),
                "response": response_body[:1024],
            }

    def _describe_archive(self, archive_path: Path) -> Optional[Dict]:
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                manifest_name = next((name for name in archive.namelist() if name.endswith("manifest.json")), None)
                if not manifest_name:
                    return None
                manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        except Exception as e:
            logger.warning("Failed to inspect flight log archive %s: %s", archive_path, str(e))
            return None

        stat = archive_path.stat()
        return {
            "archive_path": str(archive_path),
            "name": archive_path.name,
            "session": manifest.get("session"),
            "reason": manifest.get("reason"),
            "created_at": manifest.get("created_at"),
            "created_at_iso": manifest.get("created_at_iso"),
            "pixhawk_file_count": len(manifest.get("pixhawk_files") or []),
            "companion_file_count": len(manifest.get("companion_files") or []),
            "size_bytes": stat.st_size,
            "updated_at": stat.st_mtime,
        }

    def _prune_session_archives(self, session_directory: Path):
        if self.storage_config.flight_log_backup_count <= 0 or not session_directory.is_dir():
            return

        archives = sorted(
            (candidate for candidate in session_directory.glob("*.zip") if candidate.is_file()),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        for candidate in archives[self.storage_config.flight_log_backup_count :]:
            try:
                candidate.unlink()
            except OSError as e:
                logger.warning("Failed to prune flight log archive %s: %s", candidate, str(e))

    def _list_archives(self) -> List[Path]:
        if not self.base_directory.is_dir():
            return []

        archives = [
            candidate
            for candidate in self.base_directory.rglob("*.zip")
            if candidate.is_file()
        ]
        archives.sort(key=lambda candidate: (str(candidate.parent), candidate.name))
        return archives

    def _directory_size_bytes(self) -> int:
        total = 0
        if not self.base_directory.exists():
            return total
        for path in self.base_directory.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _enforce_storage_budget(self):
        max_fraction = max(0.0, min(1.0, float(getattr(self.storage_config, "flight_log_max_drive_fraction", 0.5))))
        if max_fraction <= 0.0 or not self.base_directory.exists():
            return

        try:
            usage = shutil.disk_usage(self.base_directory)
        except OSError as e:
            logger.warning("Unable to determine flight log disk usage: %s", str(e))
            return

        budget_bytes = int(usage.total * max_fraction)
        current_bytes = self._directory_size_bytes()
        if current_bytes <= budget_bytes:
            return

        for archive_path in self._list_archives():
            if current_bytes <= budget_bytes:
                break
            try:
                current_bytes -= archive_path.stat().st_size
                archive_path.unlink()
                self._cleanup_empty_parents(archive_path.parent)
            except OSError as e:
                logger.warning("Failed to prune flight log archive %s: %s", archive_path, str(e))

    def _cleanup_empty_parents(self, start_path: Path):
        current = start_path
        while current != self.base_directory and current.is_dir():
            try:
                next(current.iterdir())
                return
            except StopIteration:
                try:
                    current.rmdir()
                except OSError:
                    return
                current = current.parent
            except OSError:
                return
