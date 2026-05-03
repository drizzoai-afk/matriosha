from pathlib import Path

from matriosha.core.paths import config_dir, data_dir


def test_matriosha_home_sets_data_and_config_roots(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "memory"
    monkeypatch.setenv("MATRIOSHA_HOME", str(home))
    monkeypatch.delenv("MATRIOSHA_DATA_DIR", raising=False)
    monkeypatch.delenv("MATRIOSHA_CONFIG_DIR", raising=False)

    assert data_dir() == home / "data"
    assert config_dir() == home / "config"


def test_specific_path_overrides_win_over_matriosha_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "memory"
    data = tmp_path / "custom-data"
    config = tmp_path / "custom-config"

    monkeypatch.setenv("MATRIOSHA_HOME", str(home))
    monkeypatch.setenv("MATRIOSHA_DATA_DIR", str(data))
    monkeypatch.setenv("MATRIOSHA_CONFIG_DIR", str(config))

    assert data_dir() == data
    assert config_dir() == config
