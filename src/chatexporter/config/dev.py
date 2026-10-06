"""Entwicklungsmodus (``dev_mode: true``).

Macht den Gesamtablauf (Listing -> Abruf -> Rate-Limit-Stopp -> automatische
Fortsetzung) in wenigen Minuten und mit wenigen Anfragen testbar. Die Eingriffe
sind punktuell und aendern keine Logik: sie setzen nur die ausschlaggebenden
Werte, der Rest laeuft unveraendert:

- Listing: hoechstens ``listing_max_pages`` Seiten je Bereich; ein so gekuerztes
  Listing gilt als Teil-Listing (lokale Eintraege gelten nicht als „auf dem
  Server geloescht“).
- Abruf: nach ``conversation_fetches`` Konversationsabrufen antwortet der
  Abruf wie der Server mit HTTP 429 „Too many requests“ (simuliertes Rate-Limit).
- Rate-Limit: das Wiederauffuellen wird auf ``refill_minutes`` geschaetzt, eine
  konfigurierte Wartezeit auf hoechstens ``rate_limit_wait_minutes`` begrenzt.
- Fortsetzung: die Aufgabe startet ``continuation_delay_minutes`` nach dem Stopp.

Die Werte sind einstellbar (Abschnitt ``dev`` der Konfiguration, z. B.
``dev.listing_max_pages: 5``); die Seitengroesse ist die normale Einstellung
``providers.chatgpt.sync.listing_limit``. ``dev.conversation_fetches: 0`` schaltet das
simulierte Rate-Limit ab.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable


@dataclass(frozen=True)
class DevSettings:
    listing_max_pages: int = 3
    conversation_fetches: int = 5
    refill_minutes: int = 5
    rate_limit_wait_minutes: int = 1
    continuation_delay_minutes: int = 5


DEV = DevSettings()


def from_values(get: Callable[[str], Any]) -> DevSettings:
    """Werte aus der Konfiguration (``dev.<name>``); fehlende/ungueltige -> Standard, nie negativ.
    ``listing_max_pages`` mindestens 1; ``conversation_fetches`` 0 = kein simuliertes Rate-Limit."""
    values: dict[str, int] = {}
    for item in fields(DevSettings):
        raw = get(f"dev.{item.name}")
        try:
            number = int(raw) if raw not in (None, "") else int(item.default)
        except (TypeError, ValueError):
            number = int(item.default)
        values[item.name] = max(1 if item.name == "listing_max_pages" else 0, number)
    return DevSettings(**values)


def banner(settings: DevSettings = DEV) -> str:
    limit = (f"simuliertes Rate-Limit nach {settings.conversation_fetches} Abrufen"
             if settings.conversation_fetches else "ohne simuliertes Rate-Limit")
    return (f"DEV-MODUS AKTIV: hoechstens {settings.listing_max_pages} Listing-Seiten je Bereich, {limit}, "
            f"Fortsetzung nach {settings.continuation_delay_minutes} Minuten")


BANNER = banner(DEV)
