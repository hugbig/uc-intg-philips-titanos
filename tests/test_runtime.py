"""Startup: the manifest is found both from source and in the PyInstaller package."""

import sys
from pathlib import Path

from intg_philips_titanos.runtime import manifest_path

REPO_MANIFEST = Path(__file__).resolve().parent.parent / "driver.json"


def test_manifest_path_source():
    assert manifest_path() == REPO_MANIFEST


def test_manifest_path_frozen(monkeypatch, tmp_path):
    # Installed package: /app/driver, /app/driver.json, code under /app/_internal/.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "driver"))
    assert manifest_path() == tmp_path / "app" / "driver.json"
