from __future__ import annotations
from pathlib import Path
from typing import Any

import chatexporter.config as shared_config

from .models import (
    AuthConfig,
    AppConfig,
    ApiConfig,
    BootstrapConfig,
    BrowserConfig,
    ManualExclusionsConfig,
    StorageConfig,
    QuarantineConfig,
    SyncConfig,
)


def _bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve(path_value: str | Path | None, base: Path) -> Path | None:
    if path_value in (None, ""):
        return None
    p = Path(path_value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


#: Umgebungsvariable mit dem Pfad der gemeinsamen config.yaml.
CONFIG_ENV = "CHATEXPORTER_CONFIG"
CONFIG_NAME = "config.yaml"


def discover_config(explicit: Path | None = None, *, start: Path | None = None) -> Path:
    """Pfad der gemeinsamen config.yaml (siehe ``chatexporter.config``)."""
    import os
    if explicit is None and start is not None and not os.environ.get(CONFIG_ENV):
        found = shared_config._discover(start)
        if found is not None:
            return found
    return shared_config.locate(explicit)


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    """ChatGPT-Abschnitt ``providers.chatgpt.<name>`` (aeltere Top-Level-Abschnitte
    ``browser``/``api``/``sync`` ordnet ``chatexporter.config`` dort ein)."""
    providers = document.get("providers")
    chatgpt = providers.get("chatgpt") if isinstance(providers, dict) else None
    value = chatgpt.get(name) if isinstance(chatgpt, dict) else None
    return value if isinstance(value, dict) else {}


#: Herkunft, aus der Zugangsdaten angenommen werden (AGENTS.md: Secrets nur ueber .env/Umgebung):
#: Umgebung (``env``), die ``.env`` neben der config.yaml und die ``.env`` eines Storages (``<storage> .env``).
AUTH_KEYS = ("username", "password", "totp_secret", "totp_reference")


def _secret_origin(origin: str | None) -> bool:
    return origin == "env" or str(origin or "").endswith(".env")


def _auth_config(loaded: Any) -> AuthConfig:
    """Anmelde-Einstellungen; Zugangsdaten aus einer Config-Datei oder ``--set`` werden verworfen."""
    prefix = "providers.chatgpt.auth."
    mode = str(loaded.get(prefix + "auto_login") or "auto").lower()
    auth = AuthConfig(auto_login=mode if mode in ("auto", "on", "off") else "auto",
                      login_timeout_seconds=max(20, int(loaded.get(prefix + "login_timeout_seconds") or 120)))
    for key in AUTH_KEYS:
        value = loaded.get(prefix + key)
        if value in (None, ""):
            continue
        origin = loaded.resolved.origin(prefix + key)
        if not _secret_origin(origin):
            auth.problems.append(f"{prefix}{key} stammt aus '{origin}' und wird ignoriert – Zugangsdaten "
                                 f"nur in die .env oder Umgebung (z. B. CHATGPT_USERNAME)")
            continue
        setattr(auth, key, str(value))
    return auth


def _dev_settings(loaded: Any) -> Any:
    from chatexporter.config.dev import from_values
    return from_values(loaded.get)


def load_config(config_path: Path | None = None, overrides: dict[str, Any] | None = None) -> AppConfig:
    """ChatGPT-Konfiguration aus der gemeinsamen Konfiguration (CLI-Werte > Umgebung >
    ``.env`` > config.yaml > Standard; Umgebungsnamen siehe ``chatexporter.config.schema``)."""
    loaded = shared_config.load(config_path)
    raw = loaded.document
    base = loaded.base
    boot = raw.get("bootstrap", {}) or {}
    b = _section(raw, "browser")
    a = _section(raw, "api")
    s = raw.get("storage", {}) or {}
    sy = _section(raw, "sync")

    env_file = loaded.env_file or _resolve(boot.get("env_file") or ".env", base) or (base / ".env").resolve()
    venv_path = _resolve(boot.get("venv_path") or ".venv", base) or (base / ".venv").resolve()

    # `storage.data_root` (gemeinsamer Datenordner aller Quellen) liefert die
    # Defaults fuer raw_storage/ und .storage/ (Verwaltungsbereich des Storages).
    data_root = _resolve(s.get("data_root"), base)
    default_raw = data_root / "raw_storage" if data_root else base / "raw_storage"
    default_runtime = data_root / ".storage" if data_root else None
    # Browser-Profile sind global (nicht im Storage); nur Platzhalter ohne festes Profil.
    default_user_data = base / "browser" / "profiles" / "edge"

    edge_exe = b.get("edge_executable")
    user_data_configured = b.get("user_data_dir") not in (None, "")
    user_data = b.get("user_data_dir") or default_user_data
    kind = str(b.get("kind") or "auto").lower()
    if kind == "auto":
        kind = "edge"   # festes Profil ohne Angabe: Edge wie bisher; die Suche setzt die Art selbst
    executable = b.get("executable") or (edge_exe if kind == "edge" else None)
    # Browser-Profile und heruntergeladene Browser gehoeren nicht zu den Daten:
    # neben die config.yaml (installiert: ~/.chatexporter/browser).
    browser_root = base / "browser"
    raw_root = s.get("raw_root") or default_raw
    status_root = s.get("status_root")
    runtime_root = s.get("runtime_root") or default_runtime

    cdp_host = str(b.get("cdp_host", "127.0.0.1"))
    port = int(b.get("cdp_port", 9223))
    launch_if_needed = bool(b.get("launch_if_needed", True))
    open_url = str(b.get("open_url", "https://chatgpt.com/"))
    connect_timeout_ms = int(
        b.get("connect_timeout_ms", 15000)
    )
    interactive_reauth = bool(b.get("interactive_reauth", True))
    leave_browser_running = bool(b.get("leave_browser_running", True))
    window = str(b.get("window") or "offscreen").strip().lower()
    if window not in ("offscreen", "minimized", "visible"):
        window = "offscreen"

    api_base_url = str(a.get("base_url", "https://chatgpt.com"))
    api_timeout_ms = int(
        a.get("request_timeout_ms", 120000)
    )

    listing_limit = min(
        100,
        max(1, int(sy.get("listing_limit", 100))),
    )
    listing_mode = str(sy.get("listing_mode", "auto")).strip().lower()
    if listing_mode not in ("auto", "full", "recent"):
        raise ValueError(f"sync.listing_mode must be 'auto', 'full' or 'recent', got {listing_mode!r}")
    recent_max_pages = max(
        1,
        int(sy.get("recent_max_pages", 3)),
    )
    recent_confirm_unchanged = max(
        1,
        int(sy.get("recent_confirm_unchanged", 3)),
    )
    verify_boundary = bool(sy.get("verify_boundary", True))
    verify_max_requests = max(
        0,
        int(sy.get("verify_max_requests", 0)),
    )
    fetch_files = bool(sy.get("fetch_files", True))
    fetch_textdocs = bool(sy.get("fetch_textdocs", True))
    retry_pending_files = bool(sy.get("retry_pending_files", True))
    continue_on_error = bool(sy.get("continue_on_error", True))
    max_errors = max(
        1,
        int(sy.get("max_errors_per_run", 5)),
    )
    max_file_errors_per_run = max(
        1,
        int(sy.get("max_file_errors_per_run", 50)),
    )
    rate_limit_wait_minutes = max(
        0,
        int(sy.get("rate_limit_wait_minutes", 0)),
    )
    max_rate_limit_cycles = max(
        0,
        int(sy.get("max_rate_limit_cycles", 0)),
    )

    def _exclusions(value: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    ident = item.get("id") or item.get("conversation_id") or item.get("file_id")
                    if ident:
                        out[str(ident)] = str(item.get("reason") or "")
                elif isinstance(item, str):
                    out[item] = ""
        elif isinstance(value, dict):
            out = {str(k): str(v or "") for k, v in value.items()}
        return out

    manual = sy.get("manual_exclusions") or {}

    cfg = AppConfig(
        config_file=loaded.config_file,
        dev_mode=bool(raw.get("dev_mode")),
        dev_settings=_dev_settings(loaded),
        bootstrap=BootstrapConfig(venv_path=venv_path, env_file=env_file),
        auth=_auth_config(loaded),
        browser=BrowserConfig(
            edge_executable=_resolve(edge_exe, base),
            user_data_dir=_resolve(user_data, base) or (base / "browser" / "profiles" / "edge"),
            cdp_host=cdp_host,
            cdp_port=port,
            launch_if_needed=launch_if_needed,
            open_url=open_url,
            connect_timeout_ms=connect_timeout_ms,
            interactive_reauth=interactive_reauth,
            leave_browser_running=leave_browser_running,
            window=window,
            kind=kind,
            executable=_resolve(executable, base),
            user_data_dir_configured=user_data_configured,
            allow_download=bool(b.get("allow_download", True)),
            chrome_for_testing_url=str(b.get("chrome_for_testing_url") or BrowserConfig().chrome_for_testing_url),
            browser_root=browser_root,
        ),
        api=ApiConfig(base_url=api_base_url, request_timeout_ms=api_timeout_ms),
        storage=StorageConfig(raw_root=_resolve(raw_root, base) or (base / "workspace/raw_storage"),
                              status_root=_resolve(status_root, base),
                              runtime_root=_resolve(runtime_root, base)),
        sync=SyncConfig(
            max_file_errors_per_run=max_file_errors_per_run,
            rate_limit_wait_minutes=rate_limit_wait_minutes,
            max_rate_limit_cycles=max_rate_limit_cycles,
            quarantine=QuarantineConfig(
                enabled=bool((sy.get("quarantine") or {}).get("enabled", False)),
                min_failed_runs=max(1, int((sy.get("quarantine") or {}).get("min_failed_runs", 3))),
                min_age_hours=max(0, int((sy.get("quarantine") or {}).get("min_age_hours", 24))),
                review_after_days=max(0, int((sy.get("quarantine") or {}).get("review_after_days", 30))),
            ),
            manual_exclusions=ManualExclusionsConfig(
                conversations=_exclusions(manual.get("conversations")),
                files=_exclusions(manual.get("files")),
            ),
            listing_limit=listing_limit,
            listing_mode=listing_mode,
            recent_max_pages=recent_max_pages,
            recent_confirm_unchanged=recent_confirm_unchanged,
            verify_boundary=verify_boundary,
            verify_max_requests=verify_max_requests,
            fetch_files=fetch_files,
            fetch_textdocs=fetch_textdocs,
            retry_pending_files=retry_pending_files,
            continue_on_error=continue_on_error,
            max_errors_per_run=max_errors,
        ),
    )

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key == "raw_root": cfg.storage.raw_root = Path(value).expanduser().resolve()
        elif key == "status_root": cfg.storage.status_root = Path(value).expanduser().resolve()
        elif key == "runtime_root": cfg.storage.runtime_root = Path(value).expanduser().resolve()
        elif key == "edge_executable": cfg.browser.edge_executable = Path(value).expanduser().resolve()
        elif key == "user_data_dir":
            cfg.browser.user_data_dir = Path(value).expanduser().resolve()
            cfg.browser.user_data_dir_configured = True
        elif key == "cdp_port": cfg.browser.cdp_port = int(value)
        elif key == "fetch_files": cfg.sync.fetch_files = bool(value)
        elif key == "interactive_reauth": cfg.browser.interactive_reauth = bool(value)
    return cfg
