"""Tests for the runtime entrypoint (docker/start.py): code present + libraries match the image."""
import importlib.util
from pathlib import Path

import pytest

CANDIDATES = [Path(__file__).resolve().parents[2] / "docker" / "start.py", Path("/opt/runtime/start.py")]
START = next((p for p in CANDIDATES if p.exists()), None)
pytestmark = pytest.mark.skipif(START is None, reason="start.py not found")


@pytest.fixture
def start(monkeypatch, tmp_path):
    reqs = tmp_path / "runtime-reqs.txt"
    reqs.write_text("fastapi==0.115.0\n# comment\nldap3==2.9.1\n")
    monkeypatch.setenv("RUNTIME_REQUIREMENTS", str(reqs))
    spec = importlib.util.spec_from_file_location("codingapp_start", START)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_code(root: Path, reqs: str) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("")
    (root / "requirements.txt").write_text(reqs)
    (root / "VERSION").write_text("1.2.3\n")
    return root


def test_compatible_code(start, tmp_path):
    code = make_code(tmp_path / "code", "LDAP3==2.9.1\nfastapi==0.115.0   # web\n\n")
    assert start.check(str(code)) == ""          # order, case, comments and blanks don't matter
    assert start.version(str(code)) == "1.2.3"


def test_missing_code(start, tmp_path):
    assert "No application code" in start.check(str(tmp_path / "nothing"))


def test_library_mismatch(start, tmp_path):
    code = make_code(tmp_path / "code", "fastapi==0.115.0\nldap3==2.9.1\nredis==5.0.8\n")
    err = start.check(str(code))
    assert "redis==5.0.8" in err and "FULL package" in err
    code2 = make_code(tmp_path / "code2", "fastapi==0.116.0\nldap3==2.9.1\n")
    assert "fastapi==0.116.0" in start.check(str(code2))
