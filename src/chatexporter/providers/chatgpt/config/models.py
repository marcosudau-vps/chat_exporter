from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BootstrapConfig:
    """Local bootstrap paths used by development/setup tooling.

    These paths are intentionally separate from product data paths.  The Python
    application does not need to activate the venv itself, but exposing the
    resolved values here makes `doctor` and diagnostics deterministic.
    """

    venv_path: Path = Path(".venv")
    env_file: Path = Path(".env")


@dataclass(slots=True)
class BrowserConfig:
    edge_executable: Path | None = None
    user_data_dir: Path = Path("./browser/profiles/edge")
    #: edge | chrome | chrome_for_testing
    kind: str = "edge"
    #: Browser-Programm; None = automatisch (bei Edge auch ``edge_executable``).
    executable: Path | None = None
    #: True = Profil fest vorgegeben (Konfiguration); False = automatische Suche.
    user_data_dir_configured: bool = True
    allow_download: bool = True
    chrome_for_testing_url: str = (
        "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json")
    #: Ablage fuer Profile und heruntergeladene Browser (``<Ordner der config.yaml>/browser``).
    browser_root: Path | None = None
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9223
    launch_if_needed: bool = True
    open_url: str = "https://chatgpt.com/"
    connect_timeout_ms: int = 15000
    interactive_reauth: bool = True
    leave_browser_running: bool = True
    #: offscreen | minimized | visible – Fenster eines selbst gestarteten Browsers.
    window: str = "offscreen"

    @property
    def cdp_endpoint(self) -> str:
        return f"http://{self.cdp_host}:{self.cdp_port}"


@dataclass(slots=True)
class ApiConfig:
    base_url: str = "https://chatgpt.com"
    request_timeout_ms: int = 120000


@dataclass(slots=True)
class StorageConfig:
    raw_root: Path = Path("./workspace/raw_storage")
    #: Ablage fuer Fehler-/Abwesenheits-/Zuordnungsstatus. Bewusst NICHT im
    #: Rohdaten-Speicher; None bedeutet "<runtime_root>/status_registry".
    status_root: Path | None = None
    #: Betriebsablage (Laeufe, Staging, Statusablage, Uebersicht). Enthaelt
    #: keine Quelldaten. None bedeutet "<raw_root>/../.storage".
    runtime_root: Path | None = None


@dataclass(slots=True)
class QuarantineConfig:
    """Dauerhaft fehlschlagende Conversations/Files aussortieren.

    Bewusst als abschaltbare Option ausgelegt: eine Quarantaene bedeutet,
    dass ein Datensatz nicht mehr abgerufen wird. Das darf nie beilaeufig
    passieren, deshalb gelten mehrere Bedingungen gleichzeitig (siehe
    storage/quarantine.py).
    """

    enabled: bool = False
    # Wie viele getrennte Laeufe muessen denselben Fehler zeigen?
    min_failed_runs: int = 3
    # Wie weit muessen erster und letzter Vorfall auseinanderliegen?
    min_age_hours: int = 24
    # Nach wie vielen Tagen wird ein Eintrag erneut geprueft?
    review_after_days: int = 30


@dataclass(slots=True)
class ManualExclusionsConfig:
    """Nach manueller Pruefung bewusst ausgeschlossene Conversations/Dateien.

    Anders als die Quarantaene (automatisch, vorsichtig, mehrere Laeufe) wird
    hier sofort und bewusst uebersprungen. Jeder Eintrag traegt einen Grund.
    """

    conversations: dict[str, str] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SyncConfig:
    listing_limit: int = 100
    # `auto` (Default): leerer Bestand -> full; sonst recent, und wenn dessen
    #   Aenderungsgrenze nicht bestaetigt ist -> im selben Lauf full.
    # `full`: komplettes Listing (aktiv + archiviert), jede Seite ein Token.
    # `recent`: nur die zuletzt geaenderten aktiven Conversations
    #   (order=updated), hoechstens `recent_max_pages`; wechselt nie auf full.
    listing_mode: str = "auto"
    recent_max_pages: int = 3
    # So viele unveraenderte Eintraege muessen hinter der Aenderungsgrenze
    # folgen, bevor sie als bestaetigt gilt.
    recent_confirm_unchanged: int = 3
    # Grenzpruefung auf Turn-Ebene: unveraenderte Conversations an der Grenze
    # per Detailabruf pruefen, bis `recent_confirm_unchanged` in Folge
    # bestaetigt sind; jede Abweichung verlaengert die Pruefung.
    verify_boundary: bool = True
    # Obergrenze Detailabrufe der Grenzpruefung je Lauf (0 = unbegrenzt).
    verify_max_requests: int = 0
    fetch_files: bool = True
    fetch_textdocs: bool = True
    retry_pending_files: bool = True
    continue_on_error: bool = True
    max_errors_per_run: int = 5
    # Eigenes, groesszuegigeres Budget fuer Dateifehler. Dateien sind eine
    # wesentlich heterogenere Fehlerquelle als der Conversation-Abruf
    # (abgelaufene Anhaenge, Sonderformate). Wuerden sie dasselbe enge
    # Budget teilen, beendete ein einzelner Chat mit mehreren kaputten
    # Anhaengen den ganzen Lauf.
    max_file_errors_per_run: int = 50
    # 0 / nicht gesetzt: Lauf wird beim Rate-Limit regulaer beendet.
    # > 0: so viele Minuten warten und danach fortsetzen.
    rate_limit_wait_minutes: int = 0
    # Obergrenze fuer die Wartezyklen, damit ein Lauf nicht unbegrenzt laeuft.
    # 0 = unbegrenzt (nur sinnvoll bei bewusst ueberwachtem Dauerlauf).
    max_rate_limit_cycles: int = 0
    quarantine: QuarantineConfig = field(default_factory=QuarantineConfig)
    manual_exclusions: ManualExclusionsConfig = field(default_factory=ManualExclusionsConfig)


@dataclass(slots=True)
class AuthConfig:
    """Automatische Anmeldung. Zugangsdaten nur aus ``.env``/Umgebung; nie ausgeben (``repr=False``)."""

    #: auto | on | off
    auto_login: str = "auto"
    login_timeout_seconds: int = 120
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    totp_secret: str | None = field(default=None, repr=False)
    totp_reference: str | None = field(default=None, repr=False)
    #: Gruende, warum Zugangsdaten verworfen wurden (z. B. aus der config.yaml) – ohne Werte.
    problems: list[str] = field(default_factory=list)

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    @property
    def enabled(self) -> bool:
        return self.auto_login == "on" or (self.auto_login == "auto" and self.has_credentials)


@dataclass(slots=True)
class AppConfig:
    #: Verwendete config.yaml (zum Eintragen des gefundenen Browser-Profils).
    config_file: Path | None = None
    #: Entwicklungsmodus (siehe chatexporter.config.dev).
    dev_mode: bool = False
    #: Werte des Entwicklungsmodus (``chatexporter.config.dev.DevSettings``); None = Standard.
    dev_settings: Any = None
    bootstrap: BootstrapConfig = field(default_factory=BootstrapConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
