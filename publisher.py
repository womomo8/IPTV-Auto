
"""Publish validated IPTV M3U output with file and Git safeguards.

This module owns:
- M3U output validation.
- Safe temporary-file creation and atomic replacement.
- Protection of an existing formal output file.
- Test-mode isolation.
- Formal Git commit, push, and remote SHA verification.

It does not collect, validate, filter, or generate channel data.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import config
import sources
from models import ExitCode, FilterResult, PublishResult, RunMode


_GIT_PUBLISH_BUDGET_SECONDS = 120


class PublishError(Exception):
    """Raised when local file publication cannot be completed."""


class GitPublishError(Exception):
    """Raised when Git publication fails with a known result."""


class GitPublishUnconfirmed(Exception):
    """Raised when the remote Git publication state cannot be confirmed."""


def _validate_m3u(content: str) -> int:
    """Validate generated M3U text and return its valid channel count."""
    if not isinstance(content, str):
        raise PublishError("M3U content must be text.")

    if not content:
        raise PublishError("M3U content is empty.")

    if content.startswith("\ufeff"):
        raise PublishError("M3U content must not contain a UTF-8 BOM.")

    if "\r" in content:
        raise PublishError("M3U content must use LF line endings only.")

    if not content.endswith("\n"):
        raise PublishError("M3U content must end with LF.")

    lines = content[:-1].split("\n")

    if not lines or lines[0] != "#EXTM3U":
        raise PublishError("The first line must be #EXTM3U.")

    channel_count = 0
    index = 1

    while index < len(lines):
        extinf_line = lines[index]

        if not extinf_line.startswith("#EXTINF:"):
            raise PublishError(
                f"Expected #EXTINF at line {index + 1}."
            )

        comma_position = extinf_line.find(",")

        if comma_position < 0:
            raise PublishError(
                f"Missing channel-name separator at line {index + 1}."
            )

        display_name = extinf_line[comma_position + 1:].strip()

        if not display_name:
            raise PublishError(
                f"Channel name is empty at line {index + 1}."
            )

        url_index = index + 1

        if url_index >= len(lines):
            raise PublishError(
                f"Missing stream URL after line {index + 1}."
            )

        stream_url = lines[url_index].strip()

        if not stream_url:
            raise PublishError(
                f"Stream URL is empty at line {url_index + 1}."
            )

        try:
            normalized_url = sources.normalize_source_url(stream_url)
        except (TypeError, ValueError) as exc:
            raise PublishError(
                f"Invalid stream URL at line {url_index + 1}: {exc}"
            ) from exc

        if normalized_url != stream_url:
            raise PublishError(
                f"Stream URL is not normalized at line {url_index + 1}."
            )

        channel_count += 1
        index += 2

    if channel_count < 1:
        raise PublishError("M3U must contain at least one valid channel.")

    return channel_count


def _validate_m3u_bytes(content: bytes) -> int:
    """Decode UTF-8 strictly and validate the resulting M3U."""
    if not isinstance(content, bytes):
        raise PublishError("File content must be bytes.")

    try:
        decoded = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PublishError("M3U file is not valid UTF-8.") from exc

    return _validate_m3u(decoded)


def _write_atomically(target: Path, content: str) -> None:
    """Write a same-directory temporary file and atomically replace target."""
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Optional[Path] = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary_path = Path(temporary_name)

        encoded = content.encode("utf-8", errors="strict")

        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(encoded)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Re-read the temporary file before replacing the target.
        temporary_bytes = temporary_path.read_bytes()
        _validate_m3u_bytes(temporary_bytes)

        os.replace(temporary_path, target)
        temporary_path = None

    except (OSError, UnicodeError) as exc:
        raise PublishError(
            f"Could not safely write output file: {exc}"
        ) from exc

    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _run_git(
    repository_root: Path,
    arguments: list[str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run one Git command without invoking a shell."""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(
            cmd=["git", *arguments],
            timeout=timeout,
        )

    return subprocess.run(
        ["git", *arguments],
        cwd=str(repository_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _git_output(
    repository_root: Path,
    arguments: list[str],
    timeout: float = 10,
) -> str:
    """Run Git and return stdout, raising on command failure."""
    result = _run_git(repository_root, arguments, timeout)

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitPublishError(
            f"Git command failed ({' '.join(arguments)}): {detail}"
        )

    return result.stdout.strip()


def _get_repository_root(start: Path) -> Path:
    """Resolve the Git repository root."""
    output = _git_output(
        start,
        ["rev-parse", "--show-toplevel"],
    )

    return Path(output).resolve()


def _get_branch(repository_root: Path) -> str:
    """Resolve the branch to publish to."""
    branch = os.environ.get("GITHUB_REF_NAME", "").strip()

    if not branch:
        branch = _git_output(
            repository_root,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
        )

    if not branch:
        raise GitPublishError(
            "Could not determine the target Git branch."
        )

    check = _run_git(
        repository_root,
        ["check-ref-format", "--branch", branch],
        timeout=10,
    )

    if check.returncode != 0:
        raise GitPublishError("The target Git branch name is invalid.")

    return branch


def _publish_git(
    repository_root: Path,
    relative_target: str,
) -> tuple[bool, bool]:
    """Commit only the formal output, push, and verify the remote SHA."""
    deadline = time.monotonic() + _GIT_PUBLISH_BUDGET_SECONDS

    def remaining_time() -> float:
        return deadline - time.monotonic()

    branch = _get_branch(repository_root)

    # Check only the formal output path. Other staged or working-tree
    # files must not be included in this publication commit.
    status = _git_output(
        repository_root,
        ["status", "--porcelain", "--", relative_target],
    )

    if status:
        _git_output(
            repository_root,
            [
                "commit",
                "--only",
                "-m",
                "Update IPTV subscription",
                "--",
                relative_target,
            ],
        )

    expected_sha = _git_output(
        repository_root,
        ["rev-parse", "HEAD"],
    )

    if remaining_time() <= 0:
        raise GitPublishUnconfirmed(
            "Git publication budget expired before push."
        )

    push_error: Optional[str] = None

    try:
        push_result = _run_git(
            repository_root,
            [
                "push",
                "origin",
                f"HEAD:refs/heads/{branch}",
            ],
            timeout=remaining_time(),
        )

        if push_result.returncode != 0:
            push_error = (
                push_result.stderr.strip()
                or push_result.stdout.strip()
                or "Git push returned a non-zero exit code."
            )

    except subprocess.TimeoutExpired:
        push_error = "Git push timed out."

    except OSError as exc:
        push_error = f"Git push could not be started: {exc}"

    # Always verify the remote state after a push attempt, including
    # when the push command reports an error or times out.
    if remaining_time() <= 0:
        raise GitPublishUnconfirmed(
            "Git push consumed the publication budget; remote SHA is unknown."
        )

    try:
        remote_output = _git_output(
            repository_root,
            [
                "ls-remote",
                "origin",
                f"refs/heads/{branch}",
            ],
            timeout=remaining_time(),
        )
    except (
        GitPublishError,
        subprocess.TimeoutExpired,
        OSError,
    ) as exc:
        raise GitPublishUnconfirmed(
            f"Could not verify remote Git SHA: {exc}"
        ) from exc

    remote_sha = ""

    if remote_output:
        remote_fields = remote_output.split()

        if len(remote_fields) >= 1:
            remote_sha = remote_fields[0].strip()

    if not remote_sha:
        raise GitPublishUnconfirmed(
            "Remote branch SHA could not be read."
        )

    if remote_sha != expected_sha:
        detail = (
            f"Remote SHA {remote_sha} does not match "
            f"expected SHA {expected_sha}."
        )

        if push_error:
            detail = f"{push_error} {detail}"

        rais
