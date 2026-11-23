from pathlib import Path

from reason8.paths import REPO_ROOT, data_dir


def test_data_dir_defaults_to_the_repository(monkeypatch):
    monkeypatch.delenv("REASON8_DATA_DIR", raising=False)
    assert data_dir() == REPO_ROOT / "data"
    assert (REPO_ROOT / "pyproject.toml").is_file()


def test_data_dir_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("REASON8_DATA_DIR", str(tmp_path))
    assert data_dir() == Path(tmp_path)
