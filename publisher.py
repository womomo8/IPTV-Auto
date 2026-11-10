
"""Safe IPTV M3U publisher with one shared publication deadline."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import config
import sources
from models import ExitCode, FilterResult, PublishResult, RunMode


class PublishError(Exception):
    """Local publication failed."""


class GitPublishError(Exception):
    """Git publication failed with a known result."""


class GitPublishUnconfirmed(Exception):
    """The remote Git state could not be confirmed."""


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and _remaining(deadline) <= 0:
        raise PublishError("Publication stage budget exhausted.")


def _validate_m3u(
    content: str,
    deadline: float | None = None,
) -> int:
    """Validate M3U text and return its channel count."""
    _check_deadline(deadline)

    if not isinstance(content, str) or not content:
        raise PublishError("M3U content is empty or invalid.")

    if content.startswith("\ufeff") or "\r" in content:
        raise PublishError("M3U must be UTF-8 without BOM and use LF.")

    if not content.endswith("\n"):
        raise PublishError("M3U must end with LF.")

    lines = content[:-1].split("\n")
    if not lines or lines[0] != "#EXTM3U":
        raise PublishError("The first line must be #EXTM3U.")

    count = 0
    index = 1

    while index < len(lines):
        _check_deadline(deadline)

        extinf = lines[index]
        if not extinf.startswith("#EXTINF:") or "," not in extinf:
            raise PublishError(f"Invalid EXTINF at line {index + 1}.")

        name = extinf.split(",", 1)[1].strip()
        if not name:
            raise PublishError(f"Empty channel name at line {index + 1}.")

        if index + 1 >= len(lines):
            raise PublishError("A channel is missing its URL.")

        url = lines[index + 1].strip()
        if not url:
            raise PublishError(f"Empty URL at line {index + 2}.")

        try:
            normalized = sources.normalize_source_url(url)
        except (TypeError, ValueError) as exc:
            raise PublishError(f"Invalid URL: {exc}") from exc

        if normalized != url:
            raise PublishError(f"URL is not normalized: {url}")

        count += 1
        index += 2

    _check_deadline(deadline)

    if count == 0:
        raise PublishError("M3U contains no valid channels.")

    return count


def _validate_bytes(
    data: bytes,
    deadline: float | None = None,
) -> int:
    """Decode strict UTF-8 and validate M3U structure."""
    _check_deadline(deadline)

    try:
        return _validate_m3u(
            data.decode("utf-8", errors="strict"),
            deadline,
        )
    except UnicodeDecodeError as exc:
        raise PublishError("M3U file is not valid UTF-8.") from exc


def _atomic_write(
    target: Path,
    content: str,
    deadline: float | None = None,
) -> None:
    """Validate a same-directory temporary file before atomic replacement."""
    _check_deadline(deadline)
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_deadline(deadline)

    temporary = None

    try:
        fd, name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary = Path(name)
        _check_deadline(deadline)

        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())

        _check_deadline(deadline)
        _validate_bytes(temporary.read_bytes(), deadline)
        _check_deadline(deadline)

        os.replace(temporary, target)
        temporary = None

    except PublishError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PublishError(
            f"Safe file replacement failed: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _git(
    root: Path,
    args: list[str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run a Git command without a shell."""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(["git", *args], timeout)

    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _git_text(root: Path, args: list[str], timeout: float) -> str:
    result = _git(root, args, timeout)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitPublishError(
            f"Git command failed ({' '.join(args)}): {detail}"
        )
    return result.stdout.strip()


def _publish_git(
    root: Path,
    relative_path: str,
    deadline: float | None = None,
) -> tuple[bool, bool]:
    """Commit only the output file and verify the remote SHA.

    When called by publish(), this uses the same deadline as local
    validation and file replacement.
    """
    if deadline is None:
        deadline = time.monotonic() + config.PUBLISH_BUDGET_SECONDS

    def remaining() -> float:
        return _remaining(deadline)

    try:
        _check_deadline(deadline)

        branch = os.environ.get("GITHUB_REF_NAME", "").strip()
        if not branch:
            branch = _git_text(
                root,
                ["branch", "--show-current"],
                remaining(),
            )

        if not branch:
            raise GitPublishError("Cannot determine the Git branch.")

        check = _git(
            root,
            ["check-ref-format", "--branch", branch],
            remaining(),
        )
        if check.returncode != 0:
            raise GitPublishError("Invalid Git branch name.")

        status = _git_text(
            root,
            ["status", "--porcelain", "--", relative_path],
            remaining(),
        )

        if status:
            _git_text(
                root,
                ["add", "--", relative_path],
                remaining(),
            )
            _git_text(
                root,
                [
                    "commit",
                    "--only",
                    "-m",
                    "Update IPTV subscription",
                    "--",
                    relative_path,
                ],
                remaining(),
            )

        expected_sha = _git_text(
            root,
            ["rev-parse", "HEAD"],
            remaining(),
        )

    except subprocess.TimeoutExpired as exc:
        raise GitPublishError(
            "Git preparation exceeded the publication budget."
        ) from exc

    except PublishError as exc:
        raise GitPublishError(str(exc)) from exc

    # No push has started yet. Expiration here is a known failure,
    # not an uncertain remote result.
    if remaining() <= 0:
        raise GitPublishError(
            "Publication budget expired before Git push."
        )

    push_error = None

    try:
        pushed = _git(
            root,
            ["push", "origin", f"HEAD:refs/heads/{branch}"],
            remaining(),
        )
        if pushed.returncode != 0:
            push_error = pushed.stderr.strip() or pushed.stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as exc:
        push_error = str(exc)

    # Once push has been attempted, failure to verify is unconfirmed.
    if remaining() <= 0:
        raise GitPublishUnconfirmed(
            "Push was attempted, but no time remains to verify remote SHA."
        )

    try:
        remote = _git_text(
            root,
            ["ls-remote", "origin", f"refs/heads/{branch}"],
            remaining(),
        )
    except (GitPublishError, subprocess.TimeoutExpired, OSError) as exc:
        raise GitPublishUnconfirmed(
            f"Could not read remote SHA: {exc}"
        ) from exc

    remote_sha = remote.split()[0] if remote.split() else ""
    if not remote_sha:
        raise GitPublishUnconfirmed("Remote branch SHA is unavailable.")

    if remote_sha != expected_sha:
        detail = (
            f"Remote SHA mismatch: expected {expected_sha}, got {remote_sha}."
        )
        if push_error:
            detail += f" Push message: {push_error}"
        raise GitPublishError(detail)

    return True, True


def publish(
    filter_result: FilterResult,
    mode: RunMode,
    repository_root: Path | None = None,
) -> PublishResult:
    """Publish a FilterResult under one shared stage deadline."""
    if not isinstance(filter_result, FilterResult):
        return PublishResult(
            False,
            ExitCode.INPUT_ERROR,
            "",
            error="filter_result must be a FilterResult.",
        )

    if not isinstance(mode, RunMode):
        return PublishResult(
            False,
            ExitCode.INPUT_ERROR,
            "",
            error="mode must be RunMode.FORMAL or RunMode.TEST.",
        )

    if (
        not isinstance(filter_result.channel_count, int)
        or isinstance(filter_result.channel_count, bool)
        or filter_result.channel_count < 0
    ):
        return PublishResult(
            False,
            ExitCode.INPUT_ERROR,
            "",
            error="channel_count must be a non-negative integer.",
        )

    # The complete publication stage starts here. Every subsequent
    # local and Git operation shares this one deadline.
    deadline = time.monotonic() + config.PUBLISH_BUDGET_SECONDS

    configured = (
        config.FORMAL_OUTPUT_PATH
        if mode == RunMode.FORMAL
        else config.TEST_OUTPUT_PATH
    )
    target = Path(configured)

    try:
        _check_deadline(deadline)

        if target.is_absolute() or ".." in target.parts:
            raise PublishError(
                "Output path must stay inside the repository."
            )

        root = Path(repository_root or Path.cwd()).resolve()

        if mode == RunMode.FORMAL:
            root_text = _git_text(
                root,
                ["rev-parse", "--show-toplevel"],
                min(10.0, _remaining(deadline)),
            )
            root = Path(root_text).resolve()

        _check_deadline(deadline)

        absolute_target = (root / target).resolve()
        relative_target = absolute_target.relative_to(root)

        actual_count = _validate_m3u(
            filter_result.m3u_content,
            deadline,
        )
        if actual_count != filter_result.channel_count:
            raise PublishError(
                "Declared channel_count does not match parsed M3U."
            )

        _check_deadline(deadline)

        if mode == RunMode.FORMAL and absolute_target.exists():
            _validate_bytes(absolute_target.read_bytes(), deadline)

        _check_deadline(deadline)

        _atomic_write(
            absolute_target,
            filter_result.m3u_content,
            deadline,
        )

        _check_deadline(deadline)

    except PublishError as exc:
        return PublishResult(
            False,
            ExitCode.PUBLISH_ERROR,
            configured,
            error=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        return PublishResult(
            False,
            ExitCode.PUBLISH_ERROR,
            configured,
            error=f"Publication stage budget exhausted: {exc}",
        )
    except (OSError, ValueError, GitPublishError) as exc:
        code = (
            ExitCode.PUBLISH_ERROR
            if mode == RunMode.FORMAL
            else ExitCode.STAGE_ERROR
        )
        return PublishResult(
            False,
            code,
            configured,
            error=str(exc),
        )

    if mode == RunMode.TEST:
        return PublishResult(
            True,
            ExitCode.SUCCESS,
            configured,
            git_pushed=False,
            remote_verified=False,
        )

    try:
        pushed, verified = _publish_git(
            root,
            relative_target.as_posix(),
            deadline=deadline,
        )
        return PublishResult(
            True,
            ExitCode.SUCCESS,
            configured,
            git_pushed=pushed,
            remote_verified=verified,
        )
    except GitPublishUnconfirmed as exc:
        return PublishResult(
            False,
            ExitCode.PUBLISH_UNCONFIRMED,
            configured,
            error=str(exc),
        )
    except (GitPublishError, OSError, subprocess.TimeoutExpired) as exc:
        return PublishResult(
            False,
            ExitCode.PUBLISH_ERROR,
            configured,
            error=str(exc),
        )
