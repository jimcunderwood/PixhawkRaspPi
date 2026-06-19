"""Farm-management integration, exports, and reports."""

from __future__ import annotations

import json
import logging
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FarmIntegrationConfig:
    enabled: bool
    database_file: Path
    isoxml_output_directory: Path
    report_output_directory: Path
    agleader_endpoint: str = ""
    agleader_api_key: str = ""


class FarmIntegrationManager:
    """Builds ISOXML exports, agLeader sync payloads, and automated reports."""

    def __init__(
        self,
        config: FarmIntegrationConfig,
        payload_controller=None,
        telemetry_manager=None,
        swarm_manager=None,
        calibration_manager=None,
    ):
        self.config = config
        self.payload_controller = payload_controller
        self.telemetry_manager = telemetry_manager
        self.swarm_manager = swarm_manager
        self.calibration_manager = calibration_manager
        self.isoxml_output_directory = Path(config.isoxml_output_directory)
        self.report_output_directory = Path(config.report_output_directory)
        self.isoxml_output_directory.mkdir(parents=True, exist_ok=True)
        self.report_output_directory.mkdir(parents=True, exist_ok=True)

    def _latest_application_record(self, session: Optional[str] = None) -> Optional[Dict]:
        if not self.payload_controller:
            return None
        if session:
            record = self.payload_controller.get_application_record(session)
            if record:
                return record
        records = self.payload_controller.list_application_records()
        return records[0] if records else None

    def _build_context(self, session: Optional[str] = None) -> Dict:
        record = self._latest_application_record(session)
        telemetry_history = self.telemetry_manager.get_history(seconds=600) if self.telemetry_manager else []
        return {
            "session": session or (record or {}).get("session"),
            "application_record": record,
            "telemetry_history": telemetry_history,
            "swarm_status": self.swarm_manager.get_status() if self.swarm_manager else {},
            "swarm_coordination": self.swarm_manager.get_coordination_status() if self.swarm_manager and hasattr(self.swarm_manager, "get_coordination_status") else {},
            "calibration": self.calibration_manager.get_status() if self.calibration_manager else {},
            "generated_at": time.time(),
            "generated_at_iso": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def get_status(self) -> Dict:
        latest_report = self._latest_file(self.report_output_directory, "*.json")
        latest_isoxml = self._latest_file(self.isoxml_output_directory, "*.zip")
        return {
            "enabled": bool(self.config.enabled),
            "configured": bool(self.config.enabled or self.config.agleader_endpoint),
            "agleader_configured": bool(self.config.agleader_endpoint),
            "isoxml_output_directory": str(self.isoxml_output_directory),
            "report_output_directory": str(self.report_output_directory),
            "latest_isoxml_export": latest_isoxml,
            "latest_report": latest_report,
            "recent_isoxml_exports": self._recent_files(self.isoxml_output_directory, "*.zip"),
            "recent_reports": self._recent_files(self.report_output_directory, "*.json"),
            "updated_at": time.time(),
        }

    def _latest_file(self, directory: Path, pattern: str) -> Optional[Dict]:
        candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            return None
        candidate = candidates[0]
        stat = candidate.stat()
        return {
            "path": str(candidate),
            "name": candidate.name,
            "size_bytes": stat.st_size,
            "updated_at": stat.st_mtime,
        }

    def _recent_files(self, directory: Path, pattern: str, limit: int = 5) -> List[Dict]:
        candidates = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        recent: List[Dict] = []
        for candidate in candidates[:limit]:
            stat = candidate.stat()
            recent.append(
                {
                    "path": str(candidate),
                    "name": candidate.name,
                    "size_bytes": stat.st_size,
                    "updated_at": stat.st_mtime,
                }
            )
        return recent

    def _build_isoxml_document(self, context: Dict) -> ET.Element:
        root = ET.Element("ISOXML", attrib={"generatedAt": context["generated_at_iso"]})
        job = ET.SubElement(root, "TaskData")
        application = context.get("application_record") or {}
        ET.SubElement(job, "Session").text = str(context.get("session") or "")
        ET.SubElement(job, "FieldName").text = str((application.get("metadata") or {}).get("field_name") or "")
        ET.SubElement(job, "ProductName").text = str((application.get("metadata") or {}).get("product_name") or "")
        ET.SubElement(job, "TotalVolumeLiters").text = str(application.get("total_volume_liters") or 0.0)
        ET.SubElement(job, "ApplicationRateLPerHa").text = str(application.get("application_rate_liters_per_hectare") or "")
        boundary = (application.get("metadata") or {}).get("field_boundary") or {}
        if boundary:
            boundary_node = ET.SubElement(job, "FieldBoundary")
            for vertex in boundary.get("vertices") or []:
                ET.SubElement(
                    boundary_node,
                    "Point",
                    attrib={
                        "lat": str(vertex.get("latitude")),
                        "lon": str(vertex.get("longitude")),
                        "alt": str(vertex.get("altitude", 0.0)),
                    },
                )
        return root

    def export_isoxml(self, session: Optional[str] = None) -> Dict:
        context = self._build_context(session=session)
        root = self._build_isoxml_document(context)
        xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        timestamp = int(time.time() * 1000)
        archive_path = self.isoxml_output_directory / f"isoxml-{timestamp}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("taskdata.xml", xml_bytes)
            archive.writestr("manifest.json", json.dumps(context, indent=2, default=str))
        return {
            "session": context.get("session"),
            "archive_path": str(archive_path),
            "xml": xml_bytes.decode("utf-8"),
            "generated_at": context["generated_at"],
            "generated_at_iso": context["generated_at_iso"],
        }

    def build_agleader_payload(self, session: Optional[str] = None) -> Dict:
        context = self._build_context(session=session)
        application = context.get("application_record") or {}
        return {
            "farm_name": (application.get("metadata") or {}).get("field_name") or "Unknown Farm",
            "session": context.get("session"),
            "application": application,
            "swarm": context.get("swarm_status"),
            "coordination": context.get("swarm_coordination"),
            "calibration": context.get("calibration"),
            "telemetry_samples": len(context.get("telemetry_history") or []),
            "generated_at": context["generated_at"],
            "generated_at_iso": context["generated_at_iso"],
        }

    def sync_agleader(self, session: Optional[str] = None) -> Dict:
        payload = self.build_agleader_payload(session=session)
        timestamp = int(time.time() * 1000)
        output_path = self.report_output_directory / f"agleader-sync-{timestamp}.json"
        output_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {
            "status": "prepared" if self.config.agleader_endpoint else "queued",
            "endpoint": self.config.agleader_endpoint or None,
            "api_key_configured": bool(self.config.agleader_api_key),
            "payload_path": str(output_path),
            "payload": payload,
        }

    def generate_automated_report(self, session: Optional[str] = None) -> Dict:
        context = self._build_context(session=session)
        payload = self.build_agleader_payload(session=session)
        report = {
            "session": context.get("session"),
            "field_name": (payload.get("application") or {}).get("metadata", {}).get("field_name")
            if isinstance(payload.get("application"), dict)
            else None,
            "summary": {
                "telemetry_samples": payload.get("telemetry_samples", 0),
                "swarm_enabled": bool((payload.get("swarm") or {}).get("enabled")),
                "base_station": (context.get("calibration") or {}).get("active_base_station"),
            },
            "isoxml": self.export_isoxml(session=session),
            "agleader": payload,
            "generated_at": context["generated_at"],
            "generated_at_iso": context["generated_at_iso"],
        }
        timestamp = int(time.time() * 1000)
        output_path = self.report_output_directory / f"report-{timestamp}.json"
        output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        report["report_path"] = str(output_path)
        return report
