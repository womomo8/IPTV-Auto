
"""Tests for the shared IPv4-only network layer."""

import asyncio
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import network


class TestValidateUrl(unittest.TestCase):

    def test_normalizes_http_url(self):
        self.assertEqual(
            network._validate_url(
                "HTTP://Example.COM:80/live.ts#fragment"
            ),
            ("http://example.com/live.ts", "example.com", 80),
        )

    def test_keeps_non_default_port(self):
        self.assertEqual(
            network._validate_url(
                "http://example.com:8080/live.ts"
            )[2],
            8080,
        )

    def test_rejects_invalid_urls(self):
        urls = [
            "",
            "ftp://example.com/live.ts",
            "http://user:pass@example.com/live.ts",
            "http://[2001:4860:4860::8888]/live.ts",
            "http://example.com:0/live.ts",
            "http://example.com:65536/live.ts",
        ]
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    network._validate_url(url)


class TestResolvePublicIPv4(unittest.IsolatedAsyncioTestCase):

    async def test_accepts_public_ipv4(self):
        self.assertEqual(
            await network._resolve_public_ipv4("8.8.8.8", 80),
            ("8.8.8.8",),
        )

    async def test_rejects_private_ipv4(self):
        with self.assertRaises(ValueError):
            await network._resolve_public_ipv4("192.168.1.1", 80)

    async def test_rejects_ipv6(self):
        with self.assertRaises(ValueError):
            await network._resolve_public_ipv4(
                "2001:4860:4860::8888", 80
            )

    async def test_rejects_mixed_public_and_private_dns(self):
        records = [
            (None, None, None, None, ("8.8.8.8", 80)),
            (None, None, None, None, ("192.168.1.1", 80)),
        ]
        fake_loop = SimpleNamespace(
            getaddrinfo=AsyncMock(return_value=records)
        )

        with patch(
            "network.asyncio.get_running_loop",
            return_value=fake_loop,
        ):
            with self.assertRaises(ValueError):
                await network._resolve_public_ipv4("example.com", 80)

        fake_loop.getaddrinfo.assert_awaited_once()

    async def test_rejects_empty_dns_result(self):
        fake_loop = SimpleNamespace(
            getaddrinfo=AsyncMock(return_value=[])
        )
        with patch(
            "network.asyncio.get_running_loop",
            return_value=fake_loop,
        ):
            with self.assertRaises(OSError):
                await network._resolve_public_ipv4("example.com", 80)

        fake_loop.getaddrinfo.assert_awaited_once()


class TestPinnedResolver(unittest.IsolatedAsyncioTestCase):

    async def test_returns_only_pinned_ipv4(self):
        resolver = network._PinnedIPv4Resolver(("8.8.8.8", "1.1.1.1"))
        result = await resolver.resolve("example.com", 443, socket.AF_INET)
        self.assertEqual(
            [item["host"] for item in result],
            ["8.8.8.8", "1.1.1.1"],
        )
        self.assertTrue(
            all(item["family"] == socket.AF_INET for item in result)
        )

    async def test_rejects_ipv6_family(self):
        resolver = network._PinnedIPv4Resolver(("8.8.8.8",))
        with self.assertRaises(OSError):
            await resolver.resolve("example.com", 443, socket.AF_INET6)


class TestHeadersAndPeer(unittest.TestCase):

    def response(self, headers):
        return SimpleNamespace(
            raw_headers=headers,
            headers={
                name.decode(): value.decode()
                for name, value in headers
            },
        )

    def test_accepts_identity_encoding(self):
        network._check_headers(self.response([
            (b"Content-Type", b"video/mp2t"),
            (b"Content-Encoding", b"identity"),
        ]))

    def test_rejects_compressed_response(self):
        with self.assertRaises(ValueError):
            network._check_headers(self.response([
                (b"Content-Encoding", b"gzip"),
            ]))

    def test_rejects_too_many_headers(self):
        headers = [
            (f"X-{i}".encode(), b"value")
            for i in range(network.config.MAX_HTTP_HEADERS_COUNT + 1)
        ]
        with self.assertRaises(ValueError):
            network._check_headers(self.response(headers))

    def peer_response(self, address):
        transport = SimpleNamespace(
            get_extra_info=lambda name: (address, 12345)
        )
        return SimpleNamespace(
            connection=SimpleNamespace(transport=transport),
            _protocol=None,
        )

    def test_accepts_public_ipv4_peer(self):
        self.assertEqual(
            network._actual_remote_ip(self.peer_response("8.8.8.8")),
            "8.8.8.8",
        )

    def test_rejects_private_peer(self):
        with self.assertRaises(OSError):
            network._actual_remote_ip(
                self.peer_response("192.168.1.1")
            )

    def test_rejects_ipv6_peer(self):
        with self.assertRaises(OSError):
            network._actual_remote_ip(
                self.peer_response("2001:4860:4860::8888")
            )


class TestReadLimited(unittest.IsolatedAsyncioTestCase):

    def response(self, read, content_length=None, at_eof=False):
        return SimpleNamespace(
            content=SimpleNamespace(
                read=read,
                at_eof=lambda: at_eof,
            ),
            content_length=content_length,
        )

    async def test_reads_complete_body(self):
        response = self.response(
            AsyncMock(side_effect=[b"abc", b""]),
            at_eof=True,
        )
        data, exceeded, received = await network._read_limited(
            response, 10
        )
        self.assertEqual(data, b"abc")
        self.assertFalse(exceeded)
        self.assertEqual(received, 3)

    async def test_detects_unknown_length_limit(self):
        response = self.response(
            AsyncMock(return_value=b"abcd"),
            at_eof=False,
        )
        data, exceeded, received = await network._read_limited(
            response, 4
        )
        self.assertEqual(data, b"abcd")
        self.assertTrue(exceeded)
        self.assertEqual(received, 4)

    async def test_known_length_equal_to_limit_is_complete(self):
        response = self.response(
            AsyncMock(return_value=b"abcd"),
            content_length=4,
        )
        _, exceeded, _ = await network._read_limited(response, 4)
        self.assertFalse(exceeded)

    async def test_known_length_above_limit_is_incomplete(self):
        response = self.response(
            AsyncMock(return_value=b"abcd"),
            content_length=100,
        )
        _, exceeded, _ = await network._read_limited(response, 4)
        self.assertTrue(exceeded)

    async def test_preserves_partial_bytes_on_read_error(self):
        response = self.response(
            AsyncMock(side_effect=[
                b"partial",
                OSError("connection lost"),
            ])
        )
        with self.assertRaises(network._ResponseReadError) as context:
            await network._read_limited(response, 100)

        self.assertEqual(context.exception.content, b"partial")
        self.assertEqual(context.exception.bytes_received, 7)

    async def test_propagates_cancellation(self):
        response = self.response(
            AsyncMock(side_effect=asyncio.CancelledError())
        )
        with self.assertRaises(asyncio.CancelledError):
            await network._read_limited(response, 100)


class TestRequestBoundary(unittest.IsolatedAsyncioTestCase):

    async def test_rejects_non_positive_max_bytes(self):
        result = await network.request(
            "https://example.com/live.ts", 0
        )
        self.assertFalse(result.success)

    async def test_rejects_non_positive_timeout(self):
        result = await network.request(
            "https://example.com/live.ts", 100,
            timeout_seconds=0,
        )
        self.assertFalse(result.success)

    async def test_propagates_external_cancellation(self):
        with patch(
            "network._request_once",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await network.request(
                    "https://example.com/live.ts", 100
                )

    async def test_does_not_retry_invalid_url(self):
        with patch(
            "network._request_once",
            new_callable=AsyncMock,
        ) as request_once:
            result = await network.request(
                "ftp://example.com/live.ts", 100
            )

        self.assertFalse(result.success)
        request_once.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
