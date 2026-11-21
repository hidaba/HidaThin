import os
import sys
import json
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.i18n import (
    t,
    get_current_language,
    get_translations,
    TRANSLATIONS,
    VALID_LANGUAGES,
    DEFAULT_LANGUAGE
)
from app.system import validate_settings
from app.main import app

def test_i18n_symmetric_keys():
    """Verify that all keys in Italian translations exist in English and vice-versa."""
    it_keys = set(TRANSLATIONS["it"].keys())
    en_keys = set(TRANSLATIONS["en"].keys())

    missing_in_en = it_keys - en_keys
    missing_in_it = en_keys - it_keys

    assert not missing_in_en, f"Keys in 'it' missing in 'en': {missing_in_en}"
    assert not missing_in_it, f"Keys in 'en' missing in 'it': {missing_in_it}"

def test_t_function():
    """Test translation lookup and fallback behavior."""
    assert t("nav_home", lang="it") == "Home"
    assert t("nav_home", lang="en") == "Home"
    assert t("select_remote_pc", lang="it") == "Seleziona Computer Remoto:"
    assert t("select_remote_pc", lang="en") == "Select Remote Computer:"

    # Test formatting placeholders
    assert t("connecting_auto_countdown", lang="it", seconds=5) == "Avvio automatico tra 5s..."
    assert t("connecting_auto_countdown", lang="en", seconds=5) == "Auto-connecting in 5s..."

    # Fallback to key if not found
    assert t("non_existent_key_xyz", lang="it") == "non_existent_key_xyz"

def test_settings_validation_language():
    """Verify language validation in validate_settings."""
    # Valid languages
    ok, msg = validate_settings({"language": "it"})
    assert ok is True

    ok, msg = validate_settings({"language": "en"})
    assert ok is True

    # Invalid language rejected
    ok, err = validate_settings({"language": "fr"})
    assert ok is False
    assert "Lingua non valida" in err

def test_web_routes_context_processor():
    """Verify that Flask context processor injects i18n helpers into templates."""
    with app.test_client() as client:
        # Request main dashboard
        res = client.get("/")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "window.I18N" in html
        assert "window.CURRENT_LANG" in html
        assert "Seleziona Computer Remoto:" in html

        # Request settings page
        res = client.get("/settings")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "setting-language" in html
        assert "Italiano" in html
        assert "English" in html

def test_launcher_language_switching():
    """Verify that NativeLauncherApp reflects language changes."""
    from app.launcher import NativeLauncherApp

    with patch("app.launcher.NativeLauncherApp.refresh_all"):
        launcher = NativeLauncherApp(server_url="http://127.0.0.1:8080", windowed=True)
        try:
            assert launcher.lang == "it"
            assert launcher.lbl_sel.cget("text") == "Seleziona Computer Remoto:"

            # Switch language to English
            launcher.lang = "en"
            launcher.update_ui_language()
            assert launcher.lbl_sel.cget("text") == "Select Remote Computer:"
            assert launcher.btn_connect.cget("text") == "CONNECT"
            assert launcher.btn_nav_wifi.cget("text") == "Configure Wi-Fi"

            # Switch back to Italian
            launcher.lang = "it"
            launcher.update_ui_language()
            assert launcher.lbl_sel.cget("text") == "Seleziona Computer Remoto:"
            assert launcher.btn_connect.cget("text") == "CONNETTI"
            assert launcher.btn_nav_wifi.cget("text") == "Configura Wi-Fi"
        finally:
            launcher.root.destroy()
