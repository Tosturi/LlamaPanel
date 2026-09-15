from pathlib import Path

from app import settings as settings_module
from app.settings import ROOT, Settings, default_data_dir


def test_default_data_dir_is_outside_the_install_tree():
    data_dir = default_data_dir()
    assert ROOT not in data_dir.parents and data_dir != ROOT


def test_default_data_dir_on_windows_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_data_dir() == tmp_path / "LlamaPanel"


def test_default_data_dir_on_linux_honours_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / "llamapanel"


def test_default_data_dir_on_linux_falls_back_to_local_share(monkeypatch):
    monkeypatch.setattr(settings_module.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert default_data_dir() == Path.home() / ".local" / "share" / "llamapanel"


def test_default_data_dir_on_macos(monkeypatch):
    monkeypatch.setattr(settings_module.sys, "platform", "darwin")
    assert default_data_dir() == Path.home() / "Library" / "Application Support" / "LlamaPanel"


def test_legacy_data_dirs_include_the_old_default_next_to_run_py():
    assert ROOT / "data" in Settings().legacy_data_dirs
    assert ROOT / "data" / "presets.json" in Settings().legacy_presets_files


def test_env_data_dir_overrides_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMAPANEL_DATA_DIR", str(tmp_path))
    assert Settings.from_env().data_dir == tmp_path.resolve()
