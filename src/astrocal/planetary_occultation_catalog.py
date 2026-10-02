"""Контроль полноты: опубликованные прогнозы French & Souami (2023).

Время — геоцентрическое сближение, G/K не подменяются визуальным V.
Старые табличные прогнозы не выдаются за уточнённые локальные контакты.
"""
from __future__ import annotations

import datetime as dt
import re

from .net import fetch

BASE = "https://pds-rings.seti.org/rms-annex/french23_occult_pred/"
TARGETS = ("Jupiter", "Saturn", "Uranus", "Neptune", "Titan", "Triton")


def parse(text):
    fields = {}
    for line in text.splitlines():
        match = re.match(r"\s*(\d+)\s*-\s*(\d+)\s+\S+\s+\S+\s+(\S+)\s", line)
        if match:
            fields[match[3]] = (int(match[1]) - 1, int(match[2]))
    required = ("TARGET", "EVENTID", "UTC_CA", "STARID", "GMAG", "KMAG", "STARPOS")
    if not all(key in fields for key in required):
        raise ValueError("Неизвестный формат таблицы RMS Annex")
    out = []
    for line in text.splitlines():
        def value(key):
            a, b = fields[key]
            return line[a:b].strip()
        if value("TARGET") not in TARGETS:
            continue
        when = dt.datetime.fromisoformat(value("UTC_CA")).replace(tzinfo=dt.timezone.utc)
        out.append({"target": value("TARGET"), "source_id": value("EVENTID"),
                    "when": when, "gaia_id": value("STARID"),
                    "star_position": value("STARPOS"),
                    "g_mag": float(value("GMAG")), "k_mag": float(value("KMAG")),
                    "event_type": value("EVENTTYPE") if "EVENTTYPE" in fields else "",
                    "source_url": BASE + value("SUMMARY_PDF"),
                    "time_semantics": "predicted_closest_approach"})
    return out


def month_report(start, end):
    report = {"source": BASE, "events": [], "errors": []}
    for target in TARGETS:
        url = BASE + f"SOM/tables/{target}/{target}_predictions_MR.txt"
        try:
            response = fetch(url, ttl_hours=24 * 30, timeout=40, retries=1)
            for item in parse(response.body):
                if start <= item["when"] < end:
                    item["provenance"] = response.provenance("French & Souami 2023 / RMS Annex")
                    report["events"].append(item)
        except Exception as error:
            report["errors"].append({"target": target, "error": str(error)})
    return report
