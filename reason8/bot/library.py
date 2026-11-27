"""Our build of BARb's library (CircuitAI with the files in ai/native), for `reason8 bot build`.

The library holds the command governor, which keeps the AI within the action budget of
ADR 0008, and the live state the scripts read (``Reason8CurrentWind`` and the others in
``ai/native/LiveState.h``). ``ai/native/build.sh`` builds it from the engine's source at the
tag of the engine it will run in, for the platform of that engine: Linux x86-64
(``libSkirmishAI.so``) or Windows x86-64 (``SkirmishAI.dll``, cross-compiled in BAR's build
image). This module runs the script into a cache folder, one per engine tag and platform, and
reuses the build while the files in ai/native are unchanged. The script writes
``reason8_library.json`` next to the library: the platform, the engine tag and commit it was
built from and the SHA-256 of the library and of ai/native.

The platform is the engine's: an engine folder whose BARb has ``SkirmishAI.dll`` is a Windows
engine.

A library is chosen with ``--library``:

``build`` (the default)
    build it, or reuse the cached build, for the engine the AI is installed into. The build
    runs on Linux x86-64 only, and for Windows needs podman or docker; elsewhere it stops and
    says to pass ``stock``.
``stock``
    the engine's own BARb library, as before: no command budget, and the scripts' live state
    reads as unknown (-1).
a path
    a build folder of ``build.sh`` (or the library in it), used as it is. It must have been
    built for the engine's tag and platform.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from reason8.paths import REPO_ROOT, data_dir

NATIVE_DIR = REPO_ROOT / "ai" / "native"
BUILD_SCRIPT = NATIVE_DIR / "build.sh"
MANIFEST_NAME = "reason8_library.json"
LINUX = "linux"
WINDOWS = "windows"
#: The library's file name on each platform, as the engine loads it.
LIBRARY_NAMES = {LINUX: "libSkirmishAI.so", WINDOWS: "SkirmishAI.dll"}
STOCK = "stock"
BUILD = "build"
ENGINE_REPOSITORY = "https://github.com/beyond-all-reason/RecoilEngine"


def default_cache_dir() -> Path:
    """Where `build` keeps its builds: ``<data dir>/native/<engine tag>`` for Linux and
    ``<data dir>/native/<engine tag>-windows`` for Windows."""
    return data_dir() / "native"


def build_dir_name(tag: str, platform_name: str) -> str:
    """The cache folder of one build: the tag, and for Windows ``-windows`` after it."""
    return tag if platform_name == LINUX else f"{tag}-{platform_name}"


def engine_platform(engine_dir: Path) -> str:
    """The platform of an engine folder, from the BARb library it ships."""
    stock = engine_dir / "AI" / "Skirmish" / "BARb" / "stable"
    for platform_name, name in LIBRARY_NAMES.items():
        if (stock / name).is_file():
            return platform_name
    if (engine_dir / "spring-headless.exe").is_file():
        return WINDOWS
    return LINUX


def script_defaults(script: str | None = None) -> tuple[str, str]:
    """(engine tag, its commit) that build.sh builds when given no tag."""
    text = script if script is not None else BUILD_SCRIPT.read_text(encoding="utf-8")
    tag = re.search(r"^default_tag=(\S+)$", text, re.M)
    commit = re.search(r"^default_commit=([0-9a-f]{40})$", text, re.M)
    if not tag or not commit:
        raise SystemExit(f"{BUILD_SCRIPT} has no default_tag or default_commit")
    return tag.group(1), commit.group(1)


def engine_tag(engine_dir: Path) -> str:
    """The engine's release tag from its folder name: ``recoil_2026.09.03`` -> ``2026.09.03``."""
    return engine_dir.name.removeprefix("recoil_")


def sources_sha256(directory: Path = NATIVE_DIR) -> str:
    """The SHA-256 of the files in `directory`, as build.sh computes it: of the
    ``<sha256>  <name>`` lines of ``sha256sum``, the names in byte order."""
    lines = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(directory.iterdir(), key=lambda path: path.name.encode())
        if path.is_file()
    )
    return hashlib.sha256(lines.encode()).hexdigest()


def can_build(
    system: str | None = None,
    machine: str | None = None,
    platform_name: str = LINUX,
    which=shutil.which,
) -> bool:
    """Whether build.sh runs here for `platform_name`: on Linux x86-64 only, and for Windows
    with podman or docker to run the build image."""
    system = system or platform.system()
    machine = machine or platform.machine()
    if system != "Linux" or machine not in ("x86_64", "AMD64"):
        return False
    return platform_name == LINUX or any(which(name) for name in ("podman", "docker"))


@dataclass
class Library:
    """The library to install: `path` is None for the engine's own."""

    path: Path | None
    facts: dict = field(default_factory=dict)
    platform: str = LINUX

    @property
    def live_state(self) -> bool:
        return self.path is not None


def read_manifest(work_dir: Path) -> dict | None:
    path = work_dir / MANIFEST_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_platform(manifest: dict) -> str:
    """The platform a manifest says; Linux for one written before build.sh had platforms."""
    return manifest.get("platform", LINUX)


def check_built(work_dir: Path, tag: str, platform_name: str = LINUX) -> dict:
    """The manifest of a build in `work_dir`, after checking it is whole and for `tag` and
    `platform_name`."""
    manifest = read_manifest(work_dir)
    name = LIBRARY_NAMES[platform_name]
    library = work_dir / name
    if manifest is None:
        raise SystemExit(f"{work_dir} has no {name} and {MANIFEST_NAME} of build.sh")
    built_for = manifest_platform(manifest)
    if built_for != platform_name:
        raise SystemExit(
            f"the library in {work_dir} was built for {built_for}, "
            f"the AI is installed into a {platform_name} engine: build it for {platform_name}"
        )
    if not library.is_file():
        raise SystemExit(f"{work_dir} has no {name} and {MANIFEST_NAME} of build.sh")
    if manifest.get("engine_tag") != tag:
        raise SystemExit(
            f"the library in {work_dir} was built for engine {manifest.get('engine_tag')}, "
            f"the AI is installed for engine {tag}: build it for that engine"
        )
    if hashlib.sha256(library.read_bytes()).hexdigest() != manifest.get("library_sha256"):
        raise SystemExit(f"{library} is not the library its {MANIFEST_NAME} describes")
    return manifest


def run_build(
    work_dir: Path,
    tag: str,
    commit: str | None,
    runner=subprocess.run,
    platform_name: str = LINUX,
) -> None:
    """Run build.sh for `tag` and `platform_name` into `work_dir` (incremental when it was
    built before)."""
    default_tag, default_commit = script_defaults()
    if commit is None:
        if tag != default_tag:
            raise SystemExit(
                f"build.sh knows the commit of engine {default_tag} only; for engine {tag} "
                f"pass --engine-commit, the commit of the tag: "
                f"git ls-remote {ENGINE_REPOSITORY} 'refs/tags/{tag}*'"
            )
        commit = default_commit
    work_dir.mkdir(parents=True, exist_ok=True)
    command = ["bash", str(BUILD_SCRIPT)]
    if platform_name != LINUX:
        command += ["--platform", platform_name]
    command += [str(work_dir), tag, commit]
    environment = {**os.environ, "JOBS": os.environ.get("JOBS", "4")}
    result = runner(command, env=environment, check=False)
    if result.returncode != 0:
        raise SystemExit(f"build.sh failed ({result.returncode}): {' '.join(command)}")


def find_library(
    choice: str,
    engine_dir: Path,
    *,
    cache_dir: Path | None = None,
    engine_commit: str | None = None,
    runner=subprocess.run,
    system: str | None = None,
    machine: str | None = None,
    which=shutil.which,
) -> Library:
    """The library for an AI installed into `engine_dir`, as `--library` chose it, for the
    engine's platform."""
    tag = engine_tag(engine_dir)
    platform_name = engine_platform(engine_dir)
    name = LIBRARY_NAMES[platform_name]
    if choice == STOCK:
        return Library(
            None, {"source": STOCK, "engine_tag": tag, "platform": platform_name}, platform_name
        )
    if choice == BUILD:
        if not can_build(system, machine, platform_name, which):
            needs = "Linux x86-64" + (", with podman or docker" if platform_name != LINUX else "")
            raise SystemExit(
                f"our BARb library for {platform_name} builds on {needs} "
                f"(this is {system or platform.system()} {machine or platform.machine()}); "
                "pass --library stock for the engine's own library, without the command "
                "budget and the live state, or --library with a build made elsewhere"
            )
        work_dir = (cache_dir or default_cache_dir()) / build_dir_name(tag, platform_name)
        manifest = read_manifest(work_dir)
        current = sources_sha256()
        if (
            manifest is None
            or manifest.get("sources_sha256") != current
            or manifest_platform(manifest) != platform_name
            or not (work_dir / name).is_file()
        ):
            run_build(work_dir, tag, engine_commit, runner, platform_name)
        manifest = check_built(work_dir, tag, platform_name)
        if manifest.get("sources_sha256") != current:
            raise SystemExit(f"build.sh left a library of other sources in {work_dir}")
        source = BUILD
    else:
        path = Path(choice).resolve()
        work_dir = path.parent if path.is_file() else path
        manifest = check_built(work_dir, tag, platform_name)
        source = "path"
    facts = {
        "source": source,
        "platform": platform_name,
        "work_dir": str(work_dir),
        "engine_tag": manifest["engine_tag"],
        "engine_commit": manifest.get("engine_commit"),
        "library_sha256": manifest["library_sha256"],
        "sources_sha256": manifest.get("sources_sha256"),
        "sources_current": manifest.get("sources_sha256") == sources_sha256(),
    }
    return Library(work_dir / name, facts, platform_name)
