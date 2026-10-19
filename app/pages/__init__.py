"""
app.pages
=========

The application pages.

Every page here is backed by real functionality — there are no placeholder
screens. The navigation is:

    Overview   what the app is, what this machine can do, session activity
    Encrypt    protect images with a passphrase
    Decrypt    restore an encrypted image (step-by-step outcome)
    Verify     check an encrypted file's integrity and format
    Analyze    research metrics (entropy, correlation, histograms, NPCR/UACI)
    History    what happened in this session
    Settings   compute + crypto settings
    About      version, licence, threat-model pointer
"""

from .analyze import AnalyzePage
from .about import AboutPage
from .base import BasePage
from .crypt import DecryptPage, EncryptPage
from .history_page import HistoryPage
from .overview import OverviewPage
from .settings_page import SettingsPage
from .verify import VerifyPage

__all__ = [
    "AboutPage",
    "AnalyzePage",
    "BasePage",
    "DecryptPage",
    "EncryptPage",
    "HistoryPage",
    "OverviewPage",
    "SettingsPage",
    "VerifyPage",
]
