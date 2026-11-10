"""Central configuration for the IPTV automation project.

All shared runtime limits, budgets, network settings, output paths,
and manually supplied sources are defined in this module.

Business logic belongs to the corresponding program, not this module.
"""

# ============================================================
# 1. Manual source configuration
# ============================================================

# Each item is one HTTP/HTTPS subscription source URL.
MANUAL_SUBSCRIPTION_SOURCES: list[str] = []

# Each item is one HTTP/HTTPS live stream URL.
MANUAL_STREAM_URLS: list[str] = []


# ============================================================
# 2. Output paths
# ============================================================

FORMAL_OUTPUT_PATH = "output/iptv.m3u"
TEST_OUTPUT_PATH = "output/test/iptv-test.m3u"


# ============================================================
# 3. Source and candidate limits
# ============================================================

# Maximum number of download targets across both collection rounds.
MAX_DOWNLOAD_TARGETS = 30

# Maximum number of automatically discovered index downloads.
MAX_AUTO_INDEX_DOWNLOADS = 5

# Maximum number of retained candidates from one subscription source.
MAX_CANDIDATES_PER_SOURCE = 100

# Maximum number of globally deduplicated candidates.
MAX_CANDIDATES_TOTAL = 800


# ============================================================
# 4. Collection limits and budgets
# ============================================================

COLLECTION_BUDGET_SECONDS = 3 * 60
INDEX_DOWNLOAD_BUDGET_SECONDS = 30

MAX_CONCURRENT_DOWNLOADS = 10
DOWNLOAD_WAITING_QUEUE_LIMIT = 20

SOURCE_DOWNLOAD_TIMEOUT_SECONDS = 8

# Index and subscription download size limits.
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024


# ============================================================
# 5. Network configuration
# ============================================================

# Only HTTP and HTTPS URLs are allowed.
ALLOWED_URL_SCHEMES = ("http", "https")

# All network connections must use IPv4.
IP_VERSION = 4

# Environment and system proxy settings must not be trusted.
TRUST_ENV_PROXY = False

# HTTPS certificate verification must remain enabled.
VERIFY_TLS = True

MIN_TCP_PORT = 1
MAX_TCP_PORT = 65535

DNS_TIMEOUT_SECONDS = 2
TCP_CONNECT_TIMEOUT_SECONDS = 3
NETWORK_READ_TIMEOUT_SECONDS = 3

MAX_NETWORK_RETRIES = 1
MAX_REDIRECTS = 3


# ============================================================
# 6. HTTP response limits
# ============================================================

MAX_HTTP_HEADERS_BYTES = 64 * 1024
MAX_HTTP_HEADERS_COUNT = 64
MAX_HTTP_HEADER_LINE_BYTES = 8 * 1024

# Automatic response decompression is forbidden.
ACCEPT_ENCODING = "identity"
AUTO_DECOMPRESS = False


# ============================================================
# 7. TS/HLS validation limits
# ============================================================

CANDIDATE_VALIDATION_BUDGET_SECONDS = 8

MAX_HLS_PLAYLIST_BYTES = 256 * 1024
MAX_TS_VALIDATION_BYTES = 4 * 1024
MAX_HLS_SEGMENT_BYTES = 64 * 1024

MAX_HLS_VARIANT_PLAYLISTS = 3


# ============================================================
# 8. Detection concurrency and budget
# ============================================================

DETECTION_BUDGET_SECONDS = 11 * 60

MAX_CONCURRENT_VALIDATIONS = 20
VALIDATION_WAITING_QUEUE_LIMIT = 40


# ============================================================
# 9. Other stage budgets
# ============================================================

NORMALIZATION_BUDGET_SECONDS = 30
FILTER_BUDGET_SECONDS = 30
PUBLISH_BUDGET_SECONDS = 2 * 60
CLEANUP_BUDGET_SECONDS = 60

STAGE_BUDGET_TOTAL_SECONDS = 18 * 60

# Time reserved for startup, environment preparation, and scheduling.
STARTUP_RESERVE_SECONDS = 60

NORMAL_RUN_TARGET_SECONDS = 19 * 60
GITHUB_ACTIONS_TIMEOUT_MINUTES = 22
