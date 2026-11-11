
def _log_validation_diagnostics(validation_results) -> None:
    """Log source totals and individual candidate failure details."""
    from urllib.parse import urlsplit, urlunsplit

    def safe_url(value):
        if not value:
            return "未提供"

        try:
            parts = urlsplit(value)
            host = parts.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            if parts.port is not None:
                host = f"{host}:{parts.port}"

            return urlunsplit((
                parts.scheme,
                host,
                parts.path,
                "已隐藏" if parts.query else "",
                "",
            ))
        except (TypeError, ValueError):
            return "地址格式异常（已隐藏）"

    def safe_text(value, limit=200):
        return str(value or "").replace("\n", " ").replace("\r", " ")[:limit]

    groups = defaultdict(list)

    for result in validation_results:
        candidate = result.candidate
        source_label = candidate.source_url or candidate.url
        source_kind = candidate.source_kind.value
        groups[(source_kind, source_label)].append(result)

    for (source_kind, source_label), results in groups.items():
        total = len(results)
        passed = sum(
            1 for result in results
            if result.completed and result.passed
        )
        incomplete = sum(
            1 for result in results
            if not result.completed
        )
        failed = total - passed - incomplete

        display_source = safe_url(source_label)

        logger.info(
            "检测来源：%s | 来源类型：%s | 总数：%d | "
            "通过：%d | 失败：%d | 未完成：%d",
            display_source,
            source_kind,
            total,
            passed,
            failed,
            incomplete,
        )

        reasons = Counter(
            safe_text(result.reason or "未提供原因")
            for result in results
            if not (result.completed and result.passed)
        )

        for reason, count in reasons.most_common(8):
            logger.warning(
                "检测失败原因：来源=%s | 类型=%s | 数量=%d | 原因=%s",
                display_source,
                source_kind,
                count,
                reason,
            )

        remaining = sum(reasons.values()) - sum(
            count for _, count in reasons.most_common(8)
        )
        if remaining:
            logger.warning(
                "其他失败原因：来源=%s | 数量=%d",
                display_source,
                remaining,
            )

    # Record every failed or incomplete candidate individually.
    for result in validation_results:
        if result.completed and result.passed:
            continue

        candidate = result.candidate
        status = "未完成" if not result.completed else "失败"

        logger.warning(
            "候选验证明细：状态=%s | 频道=%s | 来源类型=%s | "
            "来源序号=%d | 候选序号=%d | 直播地址=%s | "
            "订阅来源=%s | 原因=%s",
            status,
            safe_text(candidate.name, 100),
            candidate.source_kind.value,
            candidate.source_order,
            candidate.item_order,
            safe_url(candidate.url),
            safe_url(candidate.source_url),
            safe_text(result.reason or "未提供原因"),
        )
