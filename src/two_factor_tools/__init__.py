"""Two-Factor Tools V4 (TOTP/HOTP, verschluesselter Windows-Speicher) – unveraenderte Kopie.

Herkunft: ``ChatToolSuite/.archive_zips/2FA_two_factor_tools/two_factor_tools_v4_windows/
two_factor_tools_v4_package/two_factor_tools.py`` (SHA-256 beginnt mit ``3dec9b9b042eb7cf``),
hier als ``core.py`` uebernommen. Oeffentliche API: ``REFERENCE.md``.

Projektunabhaengige Bibliothek wie ``layered_config``: kennt ChatExporter nicht.
Ohne ``cryptography`` funktionieren Base32-Secrets und ``otpauth://``-URIs; der
verschluesselte Speicher (Windows Credential Manager + Registry) braucht es.
"""

from .core import *  # noqa: F401,F403
from .core import __all__  # noqa: F401
