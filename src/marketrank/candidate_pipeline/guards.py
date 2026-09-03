"""Fail-closed path checks for pilot/full candidate output."""

from __future__ import annotations

from pathlib import Path


class UnsafeOutputPath(ValueError):
    """A large-mode output would land outside the approved scratch tree."""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def assert_large_output_path(
    output: str | Path,
    scratch_root: str | Path,
    *,
    repository_root: str | Path | None = None,
    home_root: str | Path | None = None,
) -> Path:
    """Return the resolved output or reject unsafe large-mode placement.

    The output must be a strict descendant of the explicitly supplied scratch
    root. The scratch root itself cannot be the filesystem root, the user's
    home, or the repository. Symlink resolution happens before comparison.
    """

    out = Path(output).expanduser().resolve()
    scratch = Path(scratch_root).expanduser().resolve()
    repo = (
        Path(repository_root).expanduser().resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[3]
    )
    home = Path(home_root).expanduser().resolve() if home_root is not None else Path.home().resolve()

    if scratch == Path(scratch.anchor):
        raise UnsafeOutputPath("scratch_root cannot be a filesystem root")
    if scratch == home or _inside(scratch, home):
        raise UnsafeOutputPath("scratch_root cannot be the home directory or a descendant")
    if scratch == repo or _inside(scratch, repo):
        raise UnsafeOutputPath("scratch_root cannot be the repository or a descendant")
    if out == scratch or not _inside(out, scratch):
        raise UnsafeOutputPath("large output must be a strict descendant of scratch_root")
    if out == home or _inside(out, home):
        raise UnsafeOutputPath("large output cannot resolve under the home directory")
    if out == repo or _inside(out, repo):
        raise UnsafeOutputPath("large output cannot resolve under the repository")
    return out
