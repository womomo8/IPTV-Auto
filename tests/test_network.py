"""Tests for the shared IPv4-only network layer."""

import asyncio
import ipaddress
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp

import network


class TestValidateUrl(unittest.TestCase):

    def test_normalizes_http_url(self):
        result = network._validate_url(
            "HTTP://Example.COM:80/live.ts#fragment"
        )
        self.assertEqual(
            result,
            ("http://example.com/live.ts", "example.com", 80),
        )

    def test_normalizes_https_default_port(self):
        result = network._validate_url(
            "https://Example.COM:443/live.m3u8"
        )
        self.assertEqual(
            result,
            ("https://example.com/live.m3u8", "example.com", 443),
        )

    def test_keeps_non_default_port(self):
        result = network._validate_url(
            "http://example.com:8080/live.ts"
        )
        self.assertEqual(result[2], 8080)

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            network._validate_url(" ")

    def test_rejects_unsupported_scheme(self):
        with self.assertRaises(ValueError):
            network._validate_url("ftp://example.com/live.ts")

    def test_rejects_url_userinfo(self):
        with self.assertRaises(ValueError):
            network._validate_url(
                "http://user:password@example.com/live.ts"
            )

    def test_rejects_ipv6_literal(self):
        with self.assertRaises(ValueError):
            network._validate_url("http://[2001:4860:4860::8888]/live.ts")

    def test_rejects_invalid_port(self):
        with self.assertRaises(ValueError):
            network._validate_url("http://example.com:0/live.ts")

    def test_rejects_port_above_limit(self):
        with self.assertRaises(ValueError):
            network._validate_url("http://example.com:65536/live.ts")


class TestResolvePublicIPv4(unittest.IsolatedAsyncioTestCase):

    async def test_accepts_public_ipv4_literal(self):
        result = await network._resolve_public_ipv4(
            "8.8.8.8", 80
        )
        self.assertEqual(result, ("8.8.8.8",))

    async def test_rejects_private_ipv4_literal(self):
        with self.assertRaises(ValueError):
            await network._resolve_public_ipv4(
                "192.168.1.1", 80
            )

    async def test_rejects_ipv6_literal(self):
        with self.assertRaises(ValueError):
            await network._resolve_public_ipv4(
                "2001:4860:4860::8888", 80
            )

    async def test_rejects_mixed_public_and_private_dns_results(self):
        records = [
            (None, None, None, None, ("8.8.8.8", 80)),
            (None, None, None, None, ("192.168.1.1", 80)),
        ]

        async def fake_getaddrinfo(*args, **kwargs):
            return records

        fake_loop = SimpleNamespace(
            getaddrinfo=fake_getaddrinfo
        )

        with (
            patch(
                "network.asyncio.get_running_loop",
                return_value=fake_loop,
            ),
            patch(
                "network.asyncio.wait_for",
                new_callable=AsyncMock,
                return_value=records,
            ),
        ):
            with self.assertRaises(ValueError):
                await network._resolve_public_ipv4(
                    "example.com", 80
                )

    async def test_rejects_empty_dns_result(self):
        fake_loop = SimpleNamespace(
            getaddrinfo=AsyncMock(return_value=[])
        )

        with (
            patch(
                "network.asyncio.get_running_loop",
                return_value=fake_loop,
            ),
            patch(
                "network.asyncio.wait_for",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            with self.assertRaises(OSError):
                await network._resolve_public_ipv4(
                    "example.com", 80
                )


class TestPinnedIPv4Resolver(unittest.IsolatedAsyncioTestCase):

    async def test_returns_only_pinned_ipv4_addresses(self):
        resolver = network._PinnedIPv4Resolver(
            ("8.8.8.8", "1.1.1.1")
        )

        result = await resolver.resolve(
            "example.com",
            443,
            socket.AF_INET,
        )

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
            await resolver.resolve(
                "example.com",
                443,
                socket.AF_INET6,
            )


class TestResponseHeaders(unittest.TestCase):

    def make_response(self, headers):
        return SimpleNamespace(
            raw_headers=headers,
            headers={
                name.decode("ascii"): value.decode("ascii")
                for name, value in headers
            },
        )

    def test_accepts_normal_headers(self):
        response = self.make_response([
            (b"Content-Type", b"video/mp2t"),
            (b"Content-Encoding", b"identity"),
        ])
        network._check_headers(response)

    def test_rejects_too_many_headers(self):
        headers = [
            (f"X-{index}".encode(), b"value")
            for index in range(
                network.config.MAX_HTTP_HEADERS_COUNT + 1
            )
        ]

        with self.assertRaises(ValueError):
            network._check_headers(self.make_response(headers))

    def test_rejects_compressed_response(self):
        response = self.make_response([
            (b"Content-Encoding", b"gzip"),
        ])

        with self.assertRaises(ValueError):
            network._check_headers(response)


class TestActualRemoteIP(unittest.TestCase):

    def make_response(self, address):
        transport = SimpleNamespace(
            get_extra_info=lambda name: (address, 12345)
        )
        connection = SimpleNamespace(transport=transport)

        return SimpleNamespace(
            connection=connection,
            _protocol=None,
        )

    def test_accepts_public_ipv4_peer(self):
        result = network._actual_remote_ip(
            self.make_response("8.8.8.8")
        )
        self.assertEqual(result, "8.8.8.8")

    def test_rejects_private_ipv4_peer(self):
        with self.assertRaises(OSError):
            network._actual_remote_ip(
                self.make_response("192.168.1.1")
            )

    def test_rejects_ipv6_peer(self):
        with self.assertRaises(OSError):
            network._actual_remote_ip(
                self.make_response("2001:4860:4860::8888")
            )


class TestReadLimited(unittest.IsolatedAsyncioTestCase):

    async def test_reads_complete_body(self):
        content = SimpleNamespace(
            read=AsyncMock(side_effect=[b"abc", b""]),
            at_eof=lambda: True,
        )
        response = SimpleNamespace(
            content=content,
            content_length=None,
        )

        data, exceeded, received = await network._read_limited(
            response, 10
        )

        self.assertEqual(data, b"abc")
        self.assertFalse(exceeded)
        self.assertEqual(received, 3)

    async def test_marks_unknown_length_limit_as_incomplete(self):
        content = SimpleNamespace(
            read=AsyncMock(return_value=b"abcd"),
            at_eof=lambda: False,
        )
        response = SimpleNamespace(
            content=content,
            content_length=None,
        )

        data, exceeded, received = await network._read_limited(
            response, 4
        )

        self.assertEqual(data, b"abcd")
        self.assertTrue(exceeded)
        self.assertEqual(received, 4)

    async def test_known_content_length_equal_to_limit_is_complete(self):
        content = SimpleNamespace(
            read=AsyncMock(return_value=b"abcd"),
            at_eof=lambda: False,
        )
        response = SimpleNamespace(
            content=content,
            content_length=4,
        )

        data, exceeded, received = await network._read_limited(
            response, 4
        )

        self.assertEqual(data, b"abcd")
        self.assertFalse(exceeded)
        self.assertEqual(received, 4)

    async def test_known_content_length_above_limit_is_incomplete(self):
        content = SimpleNamespace(
            read=AsyncMock(return_value=b"abcd"),
            at_eof=lambda: False,
        )
        response = SimpleNamespace(
            content=content,
            content_length=100,
        )

        data, exceeded, received = await network._read_limited(
            response, 4
        )

        self.assertEqual(data, b"abcd")
        self.assertTrue(exceeded)
        self.assertEqual(received, 4)

    async def test_preserves_bytes_after_read_error(self):
        content = SimpleNamespace(
            read=AsyncMock(
                side_effect=[b"partial", OSError("connection lost")]
            ),
            at_eof=lambda: False,
        )
        response = SimpleNamespace(
            content=content,
            content_length=None,
        )

        with self.assertRaises(network._ResponseReadError) as context:
            await network._read_limited(response, 100)

        self.assertEqual(context.exception.content, b"partial")
        self.assertEqual(context.exception.bytes_received, 7)
        self.assertEqual(context.exception.cause_name, "OSError")

    async def test_propagates_task_cancellation(self):
        content = SimpleNamespace(
            read=AsyncMock(side_effect=asyncio.CancelledError()),
            at_eof=lambda: False,
        )
        response = SimpleNamespace(
            content=content,
            content_
