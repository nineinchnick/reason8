"""Tests for choosing and building our BARb library (no compiler needed: build.sh is faked)."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from reason8.bot import library

TAG = "2026.09.03"


def test_script_defaults_of_build_sh():
    tag, commit = library.script_defaults()
    assert tag == TAG and len(commit) == 40


def test_script_defaults_need_both():
    with pytest.raises(SystemExit):
        library.script_defaults("default_tag=1\n")


def test_engine_tag():
    assert library.engine_tag(Path("engine/recoil_2026.09.03")) == TAG
    assert library.engine_tag(Path("engine/2026.07.04")) == "2026.07.04"


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="needs coreutils")
def test_sources_hash_is_the_one_build_sh_writes(tmp_path):
    for name in ("b.h", "A.cpp", "a.cpp", "_x.patch"):
        (tmp_path / name).write_text(name)
    # the pipeline of build.sh, step 5
    shell = (
        "find . -maxdepth 1 -type f -printf '%f\\n' | LC_ALL=C sort | "
        "xargs sha256sum -- | sha256sum | cut -d' ' -f1"
    )
    expected = subprocess.run(
        ["bash", "-c", shell], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert library.sources_sha256(tmp_path) == expected
    script = library.BUILD_SCRIPT.read_text(encoding="utf-8")
    for part in ("-printf '%f\\n' | LC_ALL=C sort |", "xargs sha256sum -- | sha256sum"):
        assert part in script


def test_can_build():
    assert library.can_build("Linux", "x86_64")
    assert not library.can_build("Windows", "AMD64")
    assert not library.can_build("Linux", "aarch64")
    assert not library.can_build("Darwin", "arm64")


def test_stock():
    found = library.find_library(library.STOCK, Path("engine/recoil_2026.09.03"))
    assert found.path is None and not found.live_state
    assert found.facts == {"source": "stock", "engine_tag": TAG}


def test_build_elsewhere_than_linux_says_what_to_do(tmp_path):
    with pytest.raises(SystemExit, match="--library stock"):
        library.find_library(
            library.BUILD, Path(f"recoil_{TAG}"), cache_dir=tmp_path, system="Windows"
        )


class FakeBuild:
    """Stands in for running build.sh: writes a library and its manifest."""

    def __init__(self, tag: str = TAG, sources: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.tag = tag
        self.sources = sources

    def __call__(self, command, env, check):
        self.calls.append(command)
        assert env["JOBS"]
        work_dir = Path(command[2])
        write_build(work_dir, self.tag, self.sources or library.sources_sha256())
        return subprocess.CompletedProcess(command, 0)


def write_build(work_dir: Path, tag: str, sources: str) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    content = b"library of " + tag.encode()
    (work_dir / library.LIBRARY_NAME).write_bytes(content)
    manifest = {
        "engine_tag": tag,
        "engine_commit": "0" * 40,
        "library_sha256": hashlib.sha256(content).hexdigest(),
        "sources_sha256": sources,
    }
    (work_dir / library.MANIFEST_NAME).write_text(json.dumps(manifest))


def test_build_then_reuse(tmp_path):
    runner = FakeBuild()
    engine = Path(f"engine/recoil_{TAG}")
    found = library.find_library(
        library.BUILD, engine, cache_dir=tmp_path, runner=runner, system="Linux", machine="x86_64"
    )
    assert found.path == tmp_path / TAG / library.LIBRARY_NAME and found.live_state
    assert found.facts["source"] == "build" and found.facts["sources_current"]
    assert runner.calls[0][1:] == [
        str(library.BUILD_SCRIPT),
        str(tmp_path / TAG),
        TAG,
        library.script_defaults()[1],
    ]
    library.find_library(
        library.BUILD, engine, cache_dir=tmp_path, runner=runner, system="Linux", machine="x86_64"
    )
    assert len(runner.calls) == 1  # the cached build is current


def test_build_again_when_the_sources_changed(tmp_path):
    write_build(tmp_path / TAG, TAG, "0" * 64)
    runner = FakeBuild()
    library.find_library(
        library.BUILD,
        Path(f"recoil_{TAG}"),
        cache_dir=tmp_path,
        runner=runner,
        system="Linux",
        machine="x86_64",
    )
    assert len(runner.calls) == 1


def test_build_for_another_engine_needs_its_commit(tmp_path):
    with pytest.raises(SystemExit, match="--engine-commit"):
        library.find_library(
            library.BUILD,
            Path("recoil_2026.07.04"),
            cache_dir=tmp_path,
            runner=FakeBuild("2026.07.04"),
            system="Linux",
            machine="x86_64",
        )
    runner = FakeBuild("2026.07.04")
    library.find_library(
        library.BUILD,
        Path("recoil_2026.07.04"),
        cache_dir=tmp_path,
        engine_commit="f" * 40,
        runner=runner,
        system="Linux",
        machine="x86_64",
    )
    assert runner.calls[0][-2:] == ["2026.07.04", "f" * 40]


def test_a_given_build_must_be_for_the_engine(tmp_path):
    write_build(tmp_path, "2026.07.04", library.sources_sha256())
    with pytest.raises(SystemExit, match="built for engine 2026.07.04"):
        library.find_library(str(tmp_path), Path(f"recoil_{TAG}"))
    found = library.find_library(str(tmp_path / library.LIBRARY_NAME), Path("recoil_2026.07.04"))
    assert found.facts["source"] == "path" and found.facts["sources_current"]


def test_a_given_build_must_be_whole(tmp_path):
    write_build(tmp_path, TAG, "0" * 64)
    (tmp_path / library.LIBRARY_NAME).write_bytes(b"something else")
    with pytest.raises(SystemExit, match="not the library"):
        library.find_library(str(tmp_path), Path(f"recoil_{TAG}"))
    with pytest.raises(SystemExit, match="has no"):
        library.find_library(str(tmp_path / "missing"), Path(f"recoil_{TAG}"))


def test_failed_build_stops(tmp_path):
    def failing(command, env, check):
        return subprocess.CompletedProcess(command, 2)

    with pytest.raises(SystemExit, match="build.sh failed"):
        library.find_library(
            library.BUILD,
            Path(f"recoil_{TAG}"),
            cache_dir=tmp_path,
            runner=failing,
            system="Linux",
            machine="x86_64",
        )
