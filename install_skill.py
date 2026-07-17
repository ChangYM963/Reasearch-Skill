#!/usr/bin/env python3
"""Cross-platform, dependency-free installer for discover-experimental-gaps."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable


SKILL_NAME = "discover-experimental-gaps"
RELEASE_VERSION = "1.0.0"
MIN_PYTHON = (3, 9)
BUNDLE_ROOT = Path(__file__).resolve().parent
SOURCE_SKILL = BUNDLE_ROOT / SKILL_NAME
MANIFEST_PATH = BUNDLE_ROOT / "SKILL-MANIFEST.sha256"
RELEASE_PATH = BUNDLE_ROOT / "RELEASE.json"
EVAL_ROOT = BUNDLE_ROOT / "evals"
RELEASE_FIELDS = {
    "release_format_version",
    "skill_name",
    "skill_version",
    "schema_version",
    "fingerprint_version",
    "runtime_file_count",
    "skill_tree_sha256",
    "python_minimum",
    "bundled_regression_tests",
    "created_on",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_FORBIDDEN_CHARACTERS = set('<>:"|?*')


class InstallError(RuntimeError):
    """A safe, user-actionable installation failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise InstallError(f"Cannot inspect {path}: {exc}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def files_under(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        raise InstallError(f"Skill directory is missing: {root}")
    if is_link_like(root):
        raise InstallError(f"Directory must not be a link/reparse point: {root}")

    def walk_error(error: OSError) -> None:
        raise InstallError(f"Cannot enumerate {root}: {error}") from error

    for current, directories, files in os.walk(
        root,
        followlinks=False,
        onerror=walk_error,
    ):
        current_path = Path(current)
        for name in list(directories) + list(files):
            candidate = current_path / name
            if is_link_like(candidate):
                raise InstallError(f"Links/reparse points are not allowed: {candidate}")
        for name in files:
            candidate = current_path / name
            try:
                mode = candidate.stat().st_mode
            except OSError as exc:
                raise InstallError(f"Cannot inspect file {candidate}: {exc}") from exc
            if not stat.S_ISREG(mode):
                raise InstallError(f"Only regular files are allowed: {candidate}")
            yield candidate


def validate_relative_path(relative: str) -> None:
    if not relative or relative.startswith(("/", "\\")):
        raise InstallError(f"Unsafe manifest path: {relative!r}")
    if unicodedata.normalize("NFC", relative) != relative:
        raise InstallError(f"Manifest path is not Unicode NFC: {relative}")
    components = relative.replace("\\", "/").split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise InstallError(f"Unsafe manifest path: {relative}")
    for component in components:
        if component.endswith((" ", ".")):
            raise InstallError(f"Non-portable trailing character in: {relative}")
        if any(character in WINDOWS_FORBIDDEN_CHARACTERS for character in component):
            raise InstallError(f"Windows-forbidden character in: {relative}")
        if any(ord(character) < 32 for character in component):
            raise InstallError(f"Non-portable character in: {relative}")
        basename = component.split(".", 1)[0].upper()
        if basename in WINDOWS_RESERVED_NAMES:
            raise InstallError(f"Windows-reserved path component in: {relative}")


def actual_manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    portable_names: dict[str, str] = {}
    for path in files_under(root):
        relative = path.relative_to(root).as_posix()
        validate_relative_path(relative)
        portable_key = relative.casefold()
        if portable_key in portable_names:
            raise InstallError(
                "Case-insensitive path collision: "
                f"{portable_names[portable_key]} and {relative}"
            )
        portable_names[portable_key] = relative
        result[relative] = sha256_file(path)
    return result


def load_manifest() -> dict[str, str]:
    if (
        not os.path.lexists(MANIFEST_PATH)
        or is_link_like(MANIFEST_PATH)
        or not MANIFEST_PATH.is_file()
    ):
        raise InstallError(f"Release manifest is missing: {MANIFEST_PATH}")
    result: dict[str, str] = {}
    pattern = re.compile(r"^([0-9a-f]{64})  ([^\\].*)$")
    for line_number, raw in enumerate(
        MANIFEST_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        match = pattern.fullmatch(raw)
        if not match:
            raise InstallError(f"Malformed manifest line {line_number}.")
        digest, relative = match.groups()
        relative = relative.replace("\\", "/")
        validate_relative_path(relative)
        if relative in result:
            raise InstallError(f"Duplicate manifest path: {relative}")
        result[relative] = digest
    if not result:
        raise InstallError("Release manifest is empty.")
    return result


def tree_fingerprint(manifest: dict[str, str]) -> str:
    rows = [
        f"{relative}\0{manifest[relative]}"
        for relative in sorted(manifest, key=str.casefold)
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def validate_frontmatter(skill_root: Path) -> None:
    skill_file = skill_root / "SKILL.md"
    if not skill_file.is_file():
        raise InstallError(f"SKILL.md is missing from {skill_root}")
    lines = skill_file.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise InstallError("SKILL.md must begin with YAML front matter.")
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise InstallError("SKILL.md front matter is not closed.") from exc
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*(.*)", line)
        if not match:
            raise InstallError(f"Unsupported front-matter syntax: {line!r}")
        key, value = match.groups()
        if key in fields:
            raise InstallError(f"Duplicate front-matter field: {key}")
        fields[key] = value.strip()
    if set(fields) != {"name", "description"}:
        raise InstallError(
            "SKILL.md front matter must contain only name and description."
        )
    if fields["name"] != SKILL_NAME:
        raise InstallError(
            f"Unexpected Skill name {fields['name']!r}; expected {SKILL_NAME!r}."
        )
    if not fields["description"]:
        raise InstallError("Skill description is empty.")


def load_release() -> dict[str, object]:
    if (
        not os.path.lexists(RELEASE_PATH)
        or is_link_like(RELEASE_PATH)
        or not RELEASE_PATH.is_file()
    ):
        raise InstallError(f"Release metadata is missing: {RELEASE_PATH}")
    try:
        release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Invalid release metadata: {exc}") from exc
    if not isinstance(release, dict) or set(release) != RELEASE_FIELDS:
        raise InstallError("RELEASE.json has missing or unsupported fields.")
    expected_values = {
        "release_format_version": "1.0.0",
        "skill_name": SKILL_NAME,
        "skill_version": RELEASE_VERSION,
        "schema_version": "1.0.0",
        "fingerprint_version": "1.0.0",
        "runtime_file_count": 21,
        "python_minimum": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        "bundled_regression_tests": 51,
    }
    for field, expected in expected_values.items():
        if release.get(field) != expected:
            raise InstallError(
                f"RELEASE.json field {field!r} does not match {expected!r}."
            )
    tree_hash = release.get("skill_tree_sha256")
    if not isinstance(tree_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", tree_hash):
        raise InstallError("RELEASE.json skill_tree_sha256 is invalid.")
    try:
        created_on = dt.date.fromisoformat(str(release.get("created_on")))
    except ValueError as exc:
        raise InstallError("RELEASE.json created_on is not a valid ISO date.") from exc
    if created_on > dt.datetime.now(dt.timezone.utc).date():
        raise InstallError("RELEASE.json created_on cannot be in the future.")
    return release


def validate_skill(skill_root: Path) -> tuple[int, str]:
    if os.path.lexists(skill_root) and is_link_like(skill_root):
        raise InstallError(f"Skill root must be an entity directory, not a link: {skill_root}")
    if not skill_root.is_dir():
        raise InstallError(f"Skill root is not a directory: {skill_root}")
    validate_frontmatter(skill_root)
    expected = load_manifest()
    actual = actual_manifest(skill_root)
    missing = sorted(set(expected) - set(actual), key=str.casefold)
    extra = sorted(set(actual) - set(expected), key=str.casefold)
    changed = sorted(
        (
            relative
            for relative in expected.keys() & actual.keys()
            if expected[relative] != actual[relative]
        ),
        key=str.casefold,
    )
    if missing or extra or changed:
        raise InstallError(
            "Skill bytes do not match the release manifest. "
            f"missing={missing}, extra={extra}, changed={changed}"
        )
    release = load_release()
    fingerprint = tree_fingerprint(actual)
    if release.get("runtime_file_count") != len(actual):
        raise InstallError("Release runtime_file_count is inconsistent.")
    if release.get("skill_tree_sha256") != fingerprint:
        raise InstallError("Skill tree fingerprint does not match RELEASE.json.")
    return len(actual), fingerprint


def normalize_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def paths_overlap(first: Path, second: Path) -> bool:
    first = first.resolve(strict=False)
    second = second.resolve(strict=False)
    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


def resolve_install_root(raw: str) -> Path:
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        raise InstallError("--install-root must resolve to an absolute path.")
    root = expanded.resolve(strict=False)
    home = Path.home().resolve(strict=False)
    anchor = Path(root.anchor).resolve(strict=False)
    if normalize_key(root) in {normalize_key(home), normalize_key(anchor)}:
        raise InstallError(
            "--install-root must be a dedicated skills directory, not HOME or a filesystem root."
        )
    target = root / SKILL_NAME
    protected_paths = [
        BUNDLE_ROOT.resolve(strict=False),
        SOURCE_SKILL.resolve(strict=False),
    ]
    if any(
        paths_overlap(candidate, protected)
        for candidate in (root, target)
        for protected in protected_paths
    ):
        raise InstallError(
            "--install-root and its target must not overlap the extracted release "
            "bundle or packaged Skill."
        )
    if root.exists() and not root.is_dir():
        raise InstallError(f"Install root exists but is not a directory: {root}")
    return root


def known_skill_roots(explicit_root: Path) -> list[Path]:
    candidates = [
        explicit_root,
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
    ]
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home).expanduser() / "skills")
    unique: dict[str, Path] = {}
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        unique.setdefault(normalize_key(resolved), resolved)
    return list(unique.values())


def find_collisions(roots: Iterable[Path]) -> list[Path]:
    return [
        root / SKILL_NAME
        for root in roots
        if os.path.lexists(root / SKILL_NAME)
    ]


def acquire_lock(lock_path: Path) -> tuple[int, Path]:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except FileExistsError as exc:
        raise InstallError(f"Another installation appears active: {lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
    except OSError as exc:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except OSError:
            pass
        raise InstallError(f"Cannot initialize install lock: {lock_path}") from exc
    return descriptor, lock_path


def acquire_install_lock(root: Path) -> tuple[int, Path]:
    return acquire_lock(root / f".{SKILL_NAME}.install.lock")


def acquire_coordination_lock(roots: Iterable[Path]) -> tuple[int, Path]:
    canonical_roots = "\n".join(
        sorted((normalize_key(root) for root in roots), key=str.casefold)
    )
    key = hashlib.sha256(canonical_roots.encode("utf-8")).hexdigest()[:24]
    lock_path = (
        Path(tempfile.gettempdir()).resolve(strict=False)
        / f".{SKILL_NAME}.{key}.coordination.lock"
    )
    return acquire_lock(lock_path)


def release_install_lock(descriptor: int, lock_path: Path) -> None:
    os.close(descriptor)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(
            f"INSTALL_WARNING: installed bytes are valid but lock cleanup failed: {exc}",
            file=sys.stderr,
        )


def directory_identity(path: Path) -> tuple[int, int]:
    if is_link_like(path) or not path.is_dir():
        raise InstallError(f"Expected an entity directory: {path}")
    metadata = path.lstat()
    return metadata.st_dev, metadata.st_ino


def publish_without_overwrite(staged: Path, target: Path) -> tuple[int, int]:
    try:
        target.mkdir(mode=0o755)
    except FileExistsError as exc:
        raise InstallError(f"Target appeared before publication: {target}") from exc
    identity = directory_identity(target)
    try:
        for child in staged.iterdir():
            if child.name == "SKILL.md":
                continue
            destination = target / child.name
            if child.is_dir():
                shutil.copytree(child, destination)
            elif child.is_file():
                shutil.copy2(child, destination)
            else:
                raise InstallError(f"Unsupported staged entry: {child}")
        if directory_identity(target) != identity:
            raise InstallError("Target directory identity changed during publication.")
        temporary_skill = target / ".SKILL.md.installing"
        shutil.copy2(staged / "SKILL.md", temporary_skill)
        if directory_identity(target) != identity:
            raise InstallError("Target directory identity changed before activation.")
        if os.path.lexists(target / "SKILL.md"):
            raise InstallError("SKILL.md appeared before activation.")
        os.replace(temporary_skill, target / "SKILL.md")
        return identity
    except Exception:
        if os.path.lexists(target):
            try:
                if directory_identity(target) == identity:
                    shutil.rmtree(target)
            except (InstallError, OSError):
                pass
        raise


def run_tests() -> None:
    if (
        not os.path.lexists(EVAL_ROOT)
        or is_link_like(EVAL_ROOT)
        or not EVAL_ROOT.is_dir()
    ):
        raise InstallError(f"Bundled eval directory is missing: {EVAL_ROOT}")
    eval_files = actual_manifest(EVAL_ROOT)
    expected_eval_files = {"fixtures.py", "test_gap_workflow.py"}
    if set(eval_files) != expected_eval_files:
        raise InstallError(
            "Bundled eval directory has missing or unexpected files: "
            f"{sorted(eval_files, key=str.casefold)}"
        )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    command = [
        sys.executable,
        "-B",
        "-m",
        "unittest",
        "discover",
        "-s",
        str(EVAL_ROOT),
        "-p",
        "test*.py",
    ]
    try:
        subprocess.run(
            command,
            cwd=str(BUNDLE_ROOT),
            env=environment,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise InstallError(
            f"Bundled offline tests failed with exit code {exc.returncode}."
        ) from exc


def run_quick_validate(validator: Path, skill_root: Path) -> None:
    try:
        validator = validator.expanduser().resolve(strict=True)
    except OSError as exc:
        raise InstallError(f"Cannot resolve quick_validate.py: {exc}") from exc
    if not validator.is_file():
        raise InstallError(f"quick_validate.py is not a file: {validator}")
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", str(validator), str(skill_root)],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        raise InstallError(
            "Official quick validation failed with exit code "
            f"{completed.returncode}: {detail}"
        )


def print_result(
    action: str,
    target: Path,
    roots: list[Path],
    file_count: int,
    fingerprint: str,
    tests_ran: bool,
    quick_validate_ran: bool,
) -> None:
    print(
        json.dumps(
            {
                "action": action,
                "skill": SKILL_NAME,
                "version": RELEASE_VERSION,
                "target": str(target),
                "runtime_files": file_count,
                "skill_tree_sha256": fingerprint,
                "collision_roots_checked": [str(root) for root in roots],
                "offline_tests_ran": tests_ran,
                "quick_validate_ran": quick_validate_ran,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely install or verify discover-experimental-gaps. "
            "The install root is always explicit."
        )
    )
    parser.add_argument(
        "--install-root",
        required=True,
        help="Absolute Codex skills root, for example ~/.agents/skills.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the release and collision state without writing to install roots.",
    )
    mode.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the already installed target against this release.",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run the bundled 51-test offline regression suite.",
    )
    parser.add_argument(
        "--quick-validate",
        type=Path,
        help="Optional absolute path to the target Codex quick_validate.py.",
    )
    return parser


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        raise InstallError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required."
        )
    args = build_parser().parse_args()
    root = resolve_install_root(args.install_root)
    target = root / SKILL_NAME
    roots = known_skill_roots(root)
    source_count, source_fingerprint = validate_skill(SOURCE_SKILL)

    if args.dry_run and args.quick_validate:
        raise InstallError(
            "--quick-validate is not allowed with --dry-run because an external "
            "validator is outside the installer's write guarantees."
        )
    if args.run_tests:
        run_tests()
    if args.quick_validate and not args.verify_only:
        run_quick_validate(args.quick_validate, SOURCE_SKILL)

    collisions = find_collisions(roots)
    target_key = normalize_key(target)
    other_collisions = [
        collision
        for collision in collisions
        if normalize_key(collision) != target_key
    ]

    if args.verify_only:
        if not target.is_dir():
            raise InstallError(f"Installed target is missing: {target}")
        if other_collisions:
            raise InstallError(
                "Duplicate installations exist in other roots: "
                + ", ".join(str(path) for path in other_collisions)
            )
        count, fingerprint = validate_skill(target)
        if args.quick_validate:
            run_quick_validate(args.quick_validate, target)
        print_result(
            "verified",
            target,
            roots,
            count,
            fingerprint,
            args.run_tests,
            bool(args.quick_validate),
        )
        return 0

    if collisions:
        raise InstallError(
            "Installation stopped because the Skill already exists: "
            + ", ".join(str(path) for path in collisions)
        )

    if args.dry_run:
        print_result(
            "dry-run",
            target,
            roots,
            source_count,
            source_fingerprint,
            args.run_tests,
            bool(args.quick_validate),
        )
        return 0

    coordination_descriptor, coordination_path = acquire_coordination_lock(roots)
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock_descriptor, lock_path = acquire_install_lock(root)
        try:
            locked_collisions = find_collisions(roots)
            if locked_collisions:
                raise InstallError(
                    "Installation stopped because the Skill appeared after validation: "
                    + ", ".join(str(path) for path in locked_collisions)
                )
            temporary_parent = Path(
                tempfile.mkdtemp(
                    prefix=f".{SKILL_NAME}.installing-",
                    dir=str(root),
                )
            )
            staged = temporary_parent / SKILL_NAME
            installed = False
            published_identity: tuple[int, int] | None = None
            try:
                shutil.copytree(SOURCE_SKILL, staged)
                staged_count, staged_fingerprint = validate_skill(staged)
                if (
                    staged_count != source_count
                    or staged_fingerprint != source_fingerprint
                ):
                    raise InstallError("Staged copy differs from the verified release.")
                if os.path.lexists(target):
                    raise InstallError(f"Target appeared before publication: {target}")
                published_identity = publish_without_overwrite(staged, target)
                installed = True
                count, fingerprint = validate_skill(target)
                if args.quick_validate:
                    run_quick_validate(args.quick_validate, target)
            except Exception:
                if (
                    installed
                    and published_identity is not None
                    and os.path.lexists(target)
                ):
                    try:
                        if directory_identity(target) == published_identity:
                            shutil.rmtree(target)
                    except (InstallError, OSError):
                        pass
                raise
            finally:
                if temporary_parent.exists():
                    shutil.rmtree(temporary_parent)
        finally:
            release_install_lock(lock_descriptor, lock_path)
    finally:
        release_install_lock(coordination_descriptor, coordination_path)

    print_result(
        "installed",
        target,
        roots,
        count,
        fingerprint,
        args.run_tests,
        bool(args.quick_validate),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print(f"INSTALL_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
