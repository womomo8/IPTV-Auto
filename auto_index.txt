"""Central configuration for the IPTV automation project.

All shared runtime limits, budgets, network settings,
output paths, and manually supplied sources are defined
in this module.

Business logic belongs to the corresponding program,
not this module.
"""

# ============================================================
# 1. Manual and automatic source configuration
# ============================================================

# Each item is one HTTP/HTTPS subscription source URL.
MANUAL_SUBSCRIPTION_SOURCES: list[str] = []

# Each item is one HTTP/HTTPS live stream URL.
MANUAL_STREAM_URLS: list[str] = []

# Each item is one HTTP/HTTPS URL pointing to a plain-text
# automatic subscription index file.
AUTO_INDEX_URLS: list[str] = [
    "https://raw.githubusercontent.com/womomo8/IPTV-Auto/main/auto_index.txt",
]


# ============================================================
# 2. Output paths
# ============================================================

FORMAL_OUTPUT_PATH = "output/iptv.m3u"
TEST_OUTPUT_PATH = "output/test/iptv-test.m3u"


# ============================================================
# 3. Source and candidate limits
# ============================================================

MAX_DOWNLOAD_TARGETS = 30
MAX_AUTO_INDEX_DOWNLOADS = 5

MAX_CANDIDATES_PER_SOURCE = 100
MAX_CANDIDATES_TOTAL = 800


# ============================================================
# 4. Collection limits and budgets
# ============================================================

COLLECTION_BUDGET_SECONDS = 3 * 60
INDEX_DOWNLOAD_BUDGET_SECONDS = 30

MAX_CONCURRENT_DOWNLOADS = 10
DOWNLOAD_WAITING_QUEUE_LIMIT = 20

SOURCE_DOWNLOAD_TIMEOUT_SECONDS = 8

MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024


# ============================================================
# 5. Network configuration
# ============================================================

ALLOWED_URL_SCHEMES = ("http", "https")

# IPv4-only behavior is fixed in network.py.
# It is a security requirement, not a runtime configuration switch.

TRUST_ENV_PROXY = False

# HTTPS certificate verification is always enabled in network.py.
# No configuration switch is provided to disable TLS verification.

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

# The following values define the documented budget model.
# Their consistency is checked by tests.
STAGE_BUDGET_TOTAL_SECONDS = 18 * 60
STARTUP_RESERVE_SECONDS = 60
NORMAL_RUN_TARGET_SECONDS = 19 * 60
