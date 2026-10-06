# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Spezifikation: ``chatexporter.exe`` als Ordner-Build (onedir).

Aufruf ueber ``packaging/build.py`` (setzt Arbeits- und Zielordner).
Ergebnis: ``<dist>/ChatExporter/chatexporter.exe`` + ``_internal/``.

Mitgeliefert:
- das Paket ``chatexporter`` und ``layered_config`` (alle Module, auch die nur
  dynamisch geladenen Provider),
- ``tools/task_scheduler/scheduler_manager.py`` (Zeitplanung; wird zur Laufzeit
  aus ``_internal/tools/task_scheduler/`` geladen) samt pywin32,
- der Playwright-Treiber (Hook aus pyinstaller-hooks-contrib); Browser werden
  NICHT mitgeliefert (verwendet werden Edge/Chrome des Systems bzw. Chrome for Testing),
- ``config.example.yaml`` und die Paket-Metadaten (Versionsanzeige).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (von PyInstaller gesetzt)

hiddenimports = (
    collect_submodules("chatexporter")
    + collect_submodules("layered_config")
    + collect_submodules("two_factor_tools")
    + collect_submodules("truststore")
    + collect_submodules("cryptography")
    + ["win32com", "win32com.client", "pythoncom", "pywintypes", "win32api", "win32con", "win32timezone",
       "yaml", "dotenv"]
)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "tools" / "task_scheduler" / "scheduler_manager.py"), "tools/task_scheduler"),
        (str(ROOT / "config.example.yaml"), "."),
        *copy_metadata("chatexporter-gen4"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "docs" / "THIRD_PARTY.md"), "."),
        *(item for name in ("playwright", "PyYAML", "python-dotenv", "truststore",
                            "cryptography", "cffi", "greenlet", "pyee", "pywin32")
          for item in copy_metadata(name)),
    ],
    hiddenimports=hiddenimports,
    excludes=["pytest", "_pytest", "tkinter", "unittest.mock"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="chatexporter",
    icon=str(ROOT / "assets" / "IconChatExporter.ico"),
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="ChatExporter",
)
