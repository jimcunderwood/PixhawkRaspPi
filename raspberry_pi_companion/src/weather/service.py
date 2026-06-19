"""Aviation weather briefing and preflight evaluation."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

SM_TO_M = 1609.344
FT_TO_M = 0.3048

WIND_RE = re.compile(r"^(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT$")
VIS_SM_RE = re.compile(r"^(\d+)?(?:\s+)?(\d+/\d+)?SM$")
VIS_FRAC_RE = re.compile(r"^(\d+/\d+)SM$")
CEILING_RE = re.compile(r"^(FEW|SCT|BKN|OVC)(\d{3})(?:CB|TCU)?$")
ICAO_METAR_RE = re.compile(r"^(?:METAR|SPECI)\s+([A-Z0-9]{4})\s+(.*)$")


def _fraction_to_float(value: str) -> float:
    if "/" not in value:
        return float(value)
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def _parse_visibility_sm(tokens: list[str]) -> Optional[float]:
    for index, token in enumerate(tokens):
        if token == "CAVOK":
            return 6.0

        match = VIS_SM_RE.match(token)
        if match:
            whole = match.group(1)
            fraction = match.group(2)
            value = 0.0
            if whole:
                value += float(whole)
            if fraction:
                value += _fraction_to_float(fraction)
            return value

        if token.isdigit() and index + 1 < len(tokens) and tokens[index + 1].endswith("SM"):
            fraction_token = tokens[index + 1][:-2]
            if "/" in fraction_token:
                return float(token) + _fraction_to_float(fraction_token)

        if VIS_FRAC_RE.match(token):
            return _fraction_to_float(token[:-2])

        if token.isdigit() and len(token) == 4:
            meters = int(token)
            return round(meters / SM_TO_M, 2)

    return None


def _parse_ceiling_ft(tokens: list[str]) -> Optional[int]:
    ceilings = []
    for token in tokens:
        match = CEILING_RE.match(token)
        if match:
            layer_type = match.group(1)
            base_ft = int(match.group(2)) * 100
            if layer_type in {"BKN", "OVC"}:
                ceilings.append(base_ft)
    return min(ceilings) if ceilings else None


def _parse_wind(tokens: list[str]) -> Dict[str, Optional[int | str]]:
    for token in tokens:
        match = WIND_RE.match(token)
        if match:
            direction = match.group(1)
            speed = int(match.group(2))
            gust = int(match.group(4)) if match.group(4) else None
            return {"direction": direction, "speed_kt": speed, "gust_kt": gust}
    return {"direction": None, "speed_kt": None, "gust_kt": None}


def _parse_hazards(tokens: list[str]) -> list[str]:
    hazards = []
    for token in tokens:
        if token.startswith("RMK"):
            break
        if token in {"TS", "TSRA", "TSGR", "TSGS", "FG", "FZFG", "SN", "SG", "IC", "PL", "GR", "GS", "SS", "DS", "VA"}:
            hazards.append(token)
            continue
        if token.startswith(("+", "-")):
            stripped = token[1:]
            if stripped in {"RA", "SN", "TSRA", "TSSN", "FG", "FZFG"}:
                hazards.append(token)
                continue
        if "TS" in token or token in {"BR", "HZ"}:
            hazards.append(token)
    return hazards


def _flight_category(visibility_sm: Optional[float], ceiling_ft: Optional[int]) -> Optional[str]:
    if visibility_sm is None and ceiling_ft is None:
        return None
    if (visibility_sm is not None and visibility_sm < 1.0) or (ceiling_ft is not None and ceiling_ft < 500):
        return "LIFR"
    if (visibility_sm is not None and visibility_sm < 3.0) or (ceiling_ft is not None and ceiling_ft < 1000):
        return "IFR"
    if (visibility_sm is not None and visibility_sm < 5.0) or (ceiling_ft is not None and ceiling_ft < 3000):
        return "MVFR"
    return "VFR"


@dataclass
class WeatherBriefing:
    station_id: str
    metar_raw: Optional[str]
    taf_raw: Optional[str]
    metar: Dict
    taf: Dict
    ready: bool
    blocking_reasons: list[str]
    advisories: list[str]
    source: Dict
    updated_at: float

    def to_dict(self) -> Dict:
        return {
            "station_id": self.station_id,
            "metar_raw": self.metar_raw,
            "taf_raw": self.taf_raw,
            "metar": self.metar,
            "taf": self.taf,
            "ready": self.ready,
            "blocking_reasons": self.blocking_reasons,
            "advisories": self.advisories,
            "source": self.source,
            "updated_at": self.updated_at,
            "updated_at_iso": datetime.fromtimestamp(self.updated_at, tz=timezone.utc).isoformat(),
        }


class WeatherService:
    """Fetches and evaluates aviation weather reports."""

    def __init__(self, config):
        self.config = config
        self._last_briefing: Optional[WeatherBriefing] = None

    def _render_url(self, template: str, station_id: str) -> Optional[str]:
        template = (template or "").strip()
        if not template:
            return None
        return template.format(station_id=quote(station_id), station=quote(station_id))

    def _fetch_text(self, url: str) -> Optional[str]:
        try:
            request = Request(url, headers={"User-Agent": "PixhawkRaspPi/1.0"})
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = response.read().decode("utf-8", errors="replace").strip()
                return payload or None
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("Weather fetch failed for %s: %s", url, exc)
            return None

    def fetch_reports(self, station_id: Optional[str] = None) -> Dict[str, Optional[str]]:
        station = (station_id or self.config.station_id or "").strip().upper()
        metar_url = self._render_url(self.config.metar_url_template, station)
        taf_url = self._render_url(self.config.taf_url_template, station)
        return {
            "station_id": station,
            "metar_raw": self._fetch_text(metar_url) if metar_url else None,
            "taf_raw": self._fetch_text(taf_url) if taf_url else None,
            "metar_url": metar_url,
            "taf_url": taf_url,
        }

    def parse_metar(self, raw_metar: Optional[str]) -> Dict:
        if not raw_metar:
            return {
                "raw": None,
                "station_id": None,
                "issued_at": None,
                "visibility_sm": None,
                "ceiling_ft": None,
                "wind": {"direction": None, "speed_kt": None, "gust_kt": None},
                "hazards": [],
                "flight_category": None,
            }

        line = raw_metar.strip().splitlines()[0]
        match = ICAO_METAR_RE.match(line)
        station_id = None
        report_body = line
        if match:
            station_id = match.group(1)
            report_body = match.group(2)

        tokens = report_body.split()
        issued_at = None
        for token in tokens:
            if token.endswith("Z") and len(token) in {7, 9} and token[:6].isdigit():
                issued_at = token
                break

        visibility_sm = _parse_visibility_sm(tokens)
        ceiling_ft = _parse_ceiling_ft(tokens)
        wind = _parse_wind(tokens)
        hazards = _parse_hazards(tokens)
        flight_category = _flight_category(visibility_sm, ceiling_ft)

        return {
            "raw": line,
            "station_id": station_id,
            "issued_at": issued_at,
            "visibility_sm": visibility_sm,
            "ceiling_ft": ceiling_ft,
            "wind": wind,
            "hazards": hazards,
            "flight_category": flight_category,
        }

    def parse_taf(self, raw_taf: Optional[str]) -> Dict:
        if not raw_taf:
            return {
                "raw": None,
                "station_id": None,
                "issued_at": None,
                "valid_until": None,
                "hazards": [],
                "significant_changes": [],
            }

        lines = [line.strip() for line in raw_taf.strip().splitlines() if line.strip()]
        head = lines[0]
        head_parts = head.split()
        station_id = head_parts[1] if len(head_parts) > 1 else None
        issued_at = head_parts[2] if len(head_parts) > 2 else None
        valid_until = None
        for part in head_parts:
            if "/" in part and len(part) >= 7 and part[:6].isdigit():
                valid_until = part
                break

        hazards = []
        significant_changes = []
        for line in lines[1:]:
            tokens = line.split()
            line_hazards = _parse_hazards(tokens)
            if line_hazards:
                hazards.extend(line_hazards)
            if any(token in {"TEMPO", "PROB30", "PROB40", "BECMG"} for token in tokens):
                significant_changes.append(line)

        return {
            "raw": raw_taf.strip(),
            "station_id": station_id,
            "issued_at": issued_at,
            "valid_until": valid_until,
            "hazards": sorted(set(hazards)),
            "significant_changes": significant_changes,
        }

    def build_briefing(
        self,
        station_id: Optional[str] = None,
        metar_raw: Optional[str] = None,
        taf_raw: Optional[str] = None,
    ) -> WeatherBriefing:
        station = (station_id or self.config.station_id or "").strip().upper()
        source = {"mode": "manual" if (metar_raw or taf_raw) else "config", "station_id": station}

        if not metar_raw and not taf_raw and self.config.enabled and station:
            fetched = self.fetch_reports(station)
            metar_raw = fetched["metar_raw"]
            taf_raw = fetched["taf_raw"]
            source.update(
                {
                    "mode": "fetch",
                    "metar_url": fetched["metar_url"],
                    "taf_url": fetched["taf_url"],
                }
            )

        metar = self.parse_metar(metar_raw)
        taf = self.parse_taf(taf_raw)
        blocking_reasons = []
        advisories = []

        if not metar.get("raw"):
            blocking_reasons.append("METAR is unavailable.")
        else:
            visibility = metar.get("visibility_sm")
            ceiling = metar.get("ceiling_ft")
            wind = metar.get("wind") or {}
            flight_category = metar.get("flight_category")

            if visibility is not None and visibility < self.config.min_visibility_sm:
                blocking_reasons.append(
                    f"Visibility {visibility:.2f}SM is below the configured minimum of {self.config.min_visibility_sm:.2f}SM."
                )
            if ceiling is not None and ceiling < self.config.min_ceiling_ft:
                blocking_reasons.append(
                    f"Ceiling {ceiling}ft is below the configured minimum of {int(self.config.min_ceiling_ft)}ft."
                )
            if wind.get("speed_kt") is not None and wind["speed_kt"] > self.config.max_wind_kt:
                blocking_reasons.append(
                    f"Wind speed {wind['speed_kt']}kt exceeds the configured maximum of {self.config.max_wind_kt}kt."
                )
            if wind.get("gust_kt") is not None and wind["gust_kt"] > self.config.max_gust_kt:
                blocking_reasons.append(
                    f"Wind gust {wind['gust_kt']}kt exceeds the configured maximum of {self.config.max_gust_kt}kt."
                )
            if flight_category in {"IFR", "LIFR"} and not self.config.allow_ifr:
                blocking_reasons.append(f"Current flight category is {flight_category}.")

            hazards = set(metar.get("hazards") or [])
            hazards.update(taf.get("hazards") or [])
            blocking_hazards = {
                hazard.strip().upper()
                for hazard in (self.config.blocking_hazards or "").split(",")
                if hazard.strip()
            }
            matching_hazards = sorted(hazard for hazard in hazards if hazard.upper().lstrip("+-") in blocking_hazards)
            if matching_hazards:
                blocking_reasons.append("Hazardous weather present: " + ", ".join(matching_hazards))

            if taf.get("significant_changes"):
                advisories.append("TAF contains significant changes or tempo periods.")

        updated_at = time.time()
        briefing = WeatherBriefing(
            station_id=station,
            metar_raw=metar_raw,
            taf_raw=taf_raw,
            metar=metar,
            taf=taf,
            ready=not blocking_reasons,
            blocking_reasons=blocking_reasons,
            advisories=advisories,
            source=source,
            updated_at=updated_at,
        )
        self._last_briefing = briefing
        return briefing

    def get_status(self) -> Dict:
        briefing = self._last_briefing
        return {
            "enabled": self.config.enabled,
            "station_id": self.config.station_id,
            "configured": bool(self.config.enabled and self.config.station_id),
            "last_briefing": briefing.to_dict() if briefing else None,
        }

    def load_briefing_from_file(self, path: str) -> Optional[WeatherBriefing]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.build_briefing(
            station_id=payload.get("station_id"),
            metar_raw=payload.get("metar_raw"),
            taf_raw=payload.get("taf_raw"),
        )
