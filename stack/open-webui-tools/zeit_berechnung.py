"""
title: Zeit & Berechnung
author: local
version: 0.1.0
description: Liefert aktuelles Datum/Uhrzeit fuer Europe/Berlin und einfache Datumsberechnungen.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json


class Tools:
    def aktuelle_zeit(self, timezone: str = "Europe/Berlin") -> str:
        """
        Aktuelles Datum, Uhrzeit und Wochentag abrufen.
        Nutze dieses Tool fuer Fragen wie "welches Datum haben wir heute",
        "wie spaet ist es", "welcher Wochentag ist heute" oder "heute".

        :param timezone: IANA-Zeitzone, standardmaessig Europe/Berlin.
        """
        try:
            tz = ZoneInfo(timezone or "Europe/Berlin")
        except Exception:
            tz = ZoneInfo("Europe/Berlin")

        now = datetime.now(tz)
        weekdays = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]
        result = {
            "timezone": str(tz),
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": weekdays[now.weekday()],
            "human_de": f"{weekdays[now.weekday()]}, {now.day}. {self._month_de(now.month)} {now.year}",
        }
        return json.dumps(result, ensure_ascii=False)

    def tage_bis(self, ziel_datum: str, timezone: str = "Europe/Berlin") -> str:
        """
        Berechnet die Anzahl Kalendertage von heute bis zu einem Ziel-Datum.

        :param ziel_datum: Ziel-Datum im Format YYYY-MM-DD.
        :param timezone: IANA-Zeitzone, standardmaessig Europe/Berlin.
        """
        try:
            tz = ZoneInfo(timezone or "Europe/Berlin")
        except Exception:
            tz = ZoneInfo("Europe/Berlin")

        today = datetime.now(tz).date()
        target = datetime.strptime(ziel_datum, "%Y-%m-%d").date()
        delta = (target - today).days
        return json.dumps(
            {
                "timezone": str(tz),
                "today": today.isoformat(),
                "target": target.isoformat(),
                "days_until": delta,
            },
            ensure_ascii=False,
        )

    def datum_rechnen(self, tage: int = 0, wochen: int = 0, timezone: str = "Europe/Berlin") -> str:
        """
        Rechnet von heute aus Tage oder Wochen in die Zukunft oder Vergangenheit.
        Negative Werte bedeuten Vergangenheit.

        :param tage: Anzahl Tage, positiv oder negativ.
        :param wochen: Anzahl Wochen, positiv oder negativ.
        :param timezone: IANA-Zeitzone, standardmaessig Europe/Berlin.
        """
        try:
            tz = ZoneInfo(timezone or "Europe/Berlin")
        except Exception:
            tz = ZoneInfo("Europe/Berlin")

        today = datetime.now(tz).date()
        target = today + timedelta(days=int(tage) + int(wochen) * 7)
        weekdays = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]
        return json.dumps(
            {
                "timezone": str(tz),
                "today": today.isoformat(),
                "target": target.isoformat(),
                "weekday": weekdays[target.weekday()],
                "human_de": f"{weekdays[target.weekday()]}, {target.day}. {self._month_de(target.month)} {target.year}",
            },
            ensure_ascii=False,
        )

    def _month_de(self, month: int) -> str:
        return [
            "Januar",
            "Februar",
            "März",
            "April",
            "Mai",
            "Juni",
            "Juli",
            "August",
            "September",
            "Oktober",
            "November",
            "Dezember",
        ][month - 1]
