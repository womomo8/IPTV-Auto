
"""Shared data models for the IPTV pipeline.

This module is the single source of truth for data structures exchanged
between project programs. Other modules must import these types instead
of defining duplicate interface structures.

Interface changes must be reviewed and recorded before modification.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional, Tuple


class SourceKind(str, Enum):
    MANUAL_STREAM = "manual_stream"
    MANUAL_SUBSCRIPTION = "manual_subscription"
    AUTO_INDEX = "auto_index"
    AUTO_SUBSCRIPTION = "auto_subscription"


class RunMode(str, Enum):
    FORMAL = "formal"
    TEST = "test"


class StreamType(str, Enum):
    TS = "ts"
    HLS = "hls"
    UNKNOWN = "unknown"


class ExitCode(IntEnum):
    SUCCESS = 0
    INPUT_ERROR = 1
    STAGE_ERROR = 2
    PUBLISH_ERROR = 3
    PUBLISH_UNCONFIRMED = 4


@dataclass(frozen=True)
class SourceRecord:
    url: str
    kind: SourceKind
    order: int
    name: Optional[str] = None


@dataclass(frozen=True)
class DownloadResult:
    """Result of downloading a source or subscription.

    success indicates whether the download request succeeded.
    truncated indicates whether the downloaded content is incomplete.
    """

    source: SourceRecord
    success: bool
    content: bytes = b""
    status_code: Optional[int] = None
    error: Optional[str] = None
    bytes_received: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class IndexParseResult:
    index_source: SourceRecord
    sources: Tuple[SourceRecord, ...] = ()
    invalid_count: int = 0
    messages: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    url: str
    name: str
    source_kind: SourceKind
    source_order: int
    item_order: int
    tvg_id: Optional[str] = None
    tvg_name: Optional[str] = None
    group_title: Optional[str] = None
    source_url: Optional[str] = None


@dataclass(frozen=True)
class NetworkResult:
    """Result of a network-layer request.

    success means the request completed and passed URL, DNS, public IPv4,
    and actual remote IP safety checks.

    It does not mean the live stream itself passed validation.
    HTTP status is reported separately through status_code.
    """

    success: bool
    requested_url: str
    content: bytes = b""
    final_url: Optional[str] = None
    remote_ip: Optional[str] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    bytes_received: int = 0
    redirects: Tuple[str, ...] = ()
    error: Optional[str] = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a live stream candidate.

    completed indicates whether validation finished.
    An incomplete validation must never be treated as passed.
    """

    candidate: Candidate
    passed: bool
    stream_type: StreamType = StreamType.UNKNOWN
    completed: bool = True
    reason: Optional[str] = None


@dataclass(frozen=True)
class FilterResult:
    m3u_content: str
    channel_count: int


@dataclass(frozen=True)
class PublishResult:
    success: bool
    exit_code: ExitCode
    target_path: str
    git_pushed: bool = False
    remote_verified: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class StageResult:
    stage_name: str
    elapsed_seconds: float
    success: bool
    incomplete: bool = False
    message: Optional[str] = None


@dataclass(frozen=True)
class RunSummary:
    mode: RunMode
    exit_code: ExitCode
    stage_results: Tuple[StageResult, ...] = ()
    sources_attempted: int = 0
    candidates_collected: int = 0
    candidates_validated: int = 0
    candidates_passed: int = 0
    candidates_incomplete: int = 0
    channels_published: int = 0
    incomplete: bool = False
    messages: Tuple[str, ...] = ()
