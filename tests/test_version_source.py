"""Eine einzige Versionsquelle: ``chatexporter.__version__`` (Befehlsprotokoll, Programmkopf)."""

from chatexporter import __version__


def test_program_info_and_banner_use_the_package_version():
    from chatexporter.providers.chatgpt.cli import _program_banner
    from chatexporter.raw_session_updater.config import program_info
    assert program_info()["version"] == __version__
    assert f"chatexporter {__version__} aus" in _program_banner(None)[0]
