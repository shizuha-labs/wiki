"""Regression tests for bounded, integrity-checked Wiki MCP downloads."""

from __future__ import annotations

import base64
import hashlib
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

from mcp.types import BlobResourceContents, EmbeddedResource


MCP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MCP_DIR))
os.environ.setdefault("SHIZUHA_WIKI_URL", "https://wiki.example.test")

wiki_server = importlib.import_module("wiki_server")
base_module = importlib.import_module("base")


def metadata(payload: bytes, **overrides):
    values = {
        "id": "attachment-id",
        "filename": "evidence.bin",
        "file_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "integrity_state": "verified",
        "mime_type": "application/octet-stream",
        "storage_version_id": "version-1",
    }
    values.update(overrides)
    return values


def binary_result(payload: bytes, **overrides):
    values = {
        "content": payload,
        "status_code": 200,
        "headers": {
            "Content-Length": str(len(payload)),
            "Content-Type": "application/octet-stream",
            "X-Wiki-Integrity": "verified",
            "X-Wiki-Checksum-SHA256": hashlib.sha256(payload).hexdigest(),
            "X-Wiki-Storage-Version": "version-1",
        },
    }
    values.update(overrides)
    return values


class BinaryRequestTests(unittest.TestCase):
    def setUp(self):
        self.client = base_module.ShizuhaMCPBase(
            "wiki",
            8005,
            api_url="https://wiki.example.test",
            jwt_token="test-token",
        )

    def test_preserves_exact_bytes_and_integrity_headers(self):
        response = Mock()
        response.headers = {
            "Content-Length": "4",
            "Content-Type": "application/zip",
            "X-Wiki-Integrity": "verified",
            "X-Wiki-Checksum-SHA256": "abcd",
            "X-Wiki-Storage-Version": "v1",
        }
        response.status_code = 200
        response.iter_content.return_value = [b"PK", b"12"]
        response.raise_for_status.return_value = None

        with patch.object(base_module.requests, "request", return_value=response):
            result = self.client.api_binary_request(
                "GET", "/attachments/example/download/"
            )

        self.assertEqual(result["content"], b"PK12")
        self.assertEqual(result["headers"]["X-Wiki-Integrity"], "verified")
        self.assertEqual(result["headers"]["X-Wiki-Checksum-SHA256"], "abcd")
        self.assertEqual(result["headers"]["X-Wiki-Storage-Version"], "v1")
        response.close.assert_called_once()

    def test_refuses_declared_oversize_before_streaming(self):
        response = Mock()
        response.headers = {"Content-Length": "17"}
        response.status_code = 200
        response.raise_for_status.return_value = None

        with patch.object(base_module.requests, "request", return_value=response):
            result = self.client.api_binary_request(
                "GET", "/attachments/example/download/", max_bytes=16
            )

        self.assertEqual(result["error"], "file_too_large_for_mcp")
        self.assertEqual(result["status_code"], 413)
        response.iter_content.assert_not_called()
        response.close.assert_called_once()

    def test_refuses_chunked_oversize_before_extending_bounded_buffer(self):
        response = Mock()
        response.headers = {}
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [b"1234", b"5"]

        with patch.object(base_module.requests, "request", return_value=response):
            result = self.client.api_binary_request(
                "GET", "/attachments/example/download/", max_bytes=4
            )

        self.assertEqual(result["error"], "file_too_large_for_mcp")
        self.assertEqual(result["detail"]["received_bytes"], 5)
        response.close.assert_called_once()

    def test_http_401_403_404_preserve_status_and_close_stream(self):
        for status in (401, 403, 404):
            response = Mock()
            response.headers = {}
            response.status_code = status
            response.iter_content.return_value = [b'{"detail":"denied"}']
            response.json.side_effect = AssertionError("must not materialize via json()")
            type(response).text = PropertyMock(
                side_effect=AssertionError("must not materialize via text")
            )
            with self.subTest(status=status), patch.object(
                base_module.requests, "request", return_value=response
            ):
                result = self.client.api_binary_request(
                    "GET", "/attachments/example/download/"
                )

            self.assertEqual(result["status_code"], status)
            self.assertEqual(result["detail"], {"detail": "denied"})
            response.json.assert_not_called()
            response.close.assert_called_once()

    def test_declared_oversize_http_errors_refuse_before_materializing(self):
        for status in (400, 500):
            response = Mock()
            response.headers = {"Content-Length": "17"}
            response.status_code = status
            response.json.side_effect = AssertionError("must not materialize via json()")
            type(response).text = PropertyMock(
                side_effect=AssertionError("must not materialize via text")
            )

            with self.subTest(status=status), patch.object(
                base_module.requests, "request", return_value=response
            ):
                result = self.client.api_binary_request(
                    "GET", "/attachments/example/download/", max_bytes=16
                )

            self.assertEqual(result["error"], "file_too_large_for_mcp")
            self.assertEqual(result["status_code"], 413)
            self.assertEqual(result["detail"]["upstream_status_code"], status)
            response.iter_content.assert_not_called()
            response.json.assert_not_called()
            response.close.assert_called_once()

    def test_chunked_oversize_http_errors_refuse_bounded_body(self):
        for status in (400, 500):
            response = Mock()
            response.headers = {}
            response.status_code = status
            response.iter_content.return_value = [b"1234", b"5"]
            response.json.side_effect = AssertionError("must not materialize via json()")
            type(response).text = PropertyMock(
                side_effect=AssertionError("must not materialize via text")
            )

            with self.subTest(status=status), patch.object(
                base_module.requests, "request", return_value=response
            ):
                result = self.client.api_binary_request(
                    "GET", "/attachments/example/download/", max_bytes=4
                )

            self.assertEqual(result["error"], "file_too_large_for_mcp")
            self.assertEqual(result["status_code"], 413)
            self.assertEqual(result["detail"]["received_bytes"], 5)
            self.assertEqual(result["detail"]["upstream_status_code"], status)
            response.json.assert_not_called()
            response.close.assert_called_once()

    def test_iter_content_failure_closes_response(self):
        response = Mock()
        response.headers = {}
        response.status_code = 502
        response.iter_content.side_effect = (
            base_module.requests.exceptions.ChunkedEncodingError("stream failed")
        )

        with patch.object(base_module.requests, "request", return_value=response):
            result = self.client.api_binary_request(
                "GET", "/attachments/example/download/"
            )

        self.assertEqual(result["status_code"], 502)
        self.assertIn("stream failed", result["error"])
        response.close.assert_called_once()


class AttachmentMetadataTests(unittest.TestCase):
    def test_get_attachment_uses_canonical_size_digest_and_integrity(self):
        payload = b"metadata"
        with patch.object(
            wiki_server.base, "api_request", return_value=metadata(payload)
        ):
            result = wiki_server.get_attachment("attachment-id")

        self.assertIn(f"**Size**: {len(payload)} bytes", result)
        self.assertIn(hashlib.sha256(payload).hexdigest(), result)
        self.assertIn("**Integrity**: verified", result)
        self.assertNotIn("N/A bytes", result)


class AttachmentDownloadTests(unittest.TestCase):
    def test_full_download_returns_protocol_binary_and_verified_metadata(self):
        payload = b"PK\x03\x04wiki-evidence"
        with (
            patch.object(
                wiki_server.base, "api_request", return_value=metadata(payload)
            ),
            patch.object(
                wiki_server.base,
                "api_binary_request",
                return_value=binary_result(payload),
            ),
        ):
            result = wiki_server.download_attachment("attachment-id")

        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent["returned_bytes"], len(payload))
        self.assertEqual(result.structuredContent["full_object_size"], len(payload))
        self.assertEqual(
            result.structuredContent["checksum_sha256"],
            hashlib.sha256(payload).hexdigest(),
        )
        embedded = next(
            item for item in result.content if isinstance(item, EmbeddedResource)
        )
        self.assertIsInstance(embedded.resource, BlobResourceContents)
        self.assertEqual(base64.b64decode(embedded.resource.blob), payload)

    def test_large_attachment_requires_explicit_bounded_range_before_stream(self):
        large_size = 16 * 1024 * 1024 + 1
        with (
            patch.object(
                wiki_server.base,
                "api_request",
                return_value=metadata(b"", file_size=large_size, sha256="a" * 64),
            ),
            patch.object(wiki_server.base, "api_binary_request") as request,
        ):
            result = wiki_server.download_attachment("attachment-id")

        self.assertTrue(result.isError)
        self.assertIn("exceeds the 16 MiB", result.content[0].text)
        request.assert_not_called()

    def test_valid_range_is_bounded_and_decodes_exact_bytes(self):
        whole = b"0123456789abcdef"
        chunk = whole[4:10]
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Range": f"bytes 4-9/{len(whole)}",
            "X-Wiki-Integrity": "partial-range",
            "X-Wiki-Checksum-SHA256": hashlib.sha256(whole).hexdigest(),
            "X-Wiki-Storage-Version": "version-1",
        }
        with (
            patch.object(
                wiki_server.base, "api_request", return_value=metadata(whole)
            ),
            patch.object(
                wiki_server.base,
                "api_binary_request",
                return_value={"content": chunk, "status_code": 206, "headers": headers},
            ) as request,
        ):
            result = wiki_server.download_attachment(
                "attachment-id", offset_bytes=4, length_bytes=6
            )

        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent["content_range"], "bytes 4-9/16")
        request.assert_called_once_with(
            "GET",
            "/attachments/attachment-id/download/",
            extra_headers={"Range": "bytes=4-9"},
            max_bytes=16 * 1024 * 1024,
        )
        embedded = next(
            item for item in result.content if isinstance(item, EmbeddedResource)
        )
        self.assertEqual(base64.b64decode(embedded.resource.blob), chunk)

    def test_invalid_ranges_fail_before_binary_request(self):
        payload = b"01234567"
        invalid = [
            {"offset_bytes": -1},
            {"length_bytes": 0},
            {"length_bytes": 16 * 1024 * 1024 + 1},
            {"offset_bytes": len(payload)},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), patch.object(
                wiki_server.base, "api_request", return_value=metadata(payload)
            ), patch.object(wiki_server.base, "api_binary_request") as request:
                result = wiki_server.download_attachment("attachment-id", **kwargs)
                self.assertTrue(result.isError)
                request.assert_not_called()

    def test_checksum_or_size_mismatch_fails_closed_without_resource(self):
        payload = b"authoritative"
        cases = [
            binary_result(payload + b"!"),
            binary_result(
                payload,
                headers={
                    **binary_result(payload)["headers"],
                    "X-Wiki-Checksum-SHA256": "f" * 64,
                },
            ),
        ]
        for returned in cases:
            with self.subTest(returned=returned), patch.object(
                wiki_server.base, "api_request", return_value=metadata(payload)
            ), patch.object(
                wiki_server.base, "api_binary_request", return_value=returned
            ):
                result = wiki_server.download_attachment("attachment-id")
                self.assertTrue(result.isError)
                self.assertFalse(
                    any(isinstance(item, EmbeddedResource) for item in result.content)
                )

    def test_mime_falls_back_to_application_octet_stream(self):
        payload = b"fallback"
        returned = binary_result(payload)
        returned["headers"].pop("Content-Type")
        with (
            patch.object(
                wiki_server.base,
                "api_request",
                return_value=metadata(payload, mime_type=""),
            ),
            patch.object(
                wiki_server.base, "api_binary_request", return_value=returned
            ),
        ):
            result = wiki_server.download_attachment("attachment-id")

        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent["mime_type"], "application/octet-stream")

    def test_http_401_403_404_are_returned_as_errors(self):
        payload = b"denied"
        for status in (401, 403, 404):
            with self.subTest(status=status), patch.object(
                wiki_server.base, "api_request", return_value=metadata(payload)
            ), patch.object(
                wiki_server.base,
                "api_binary_request",
                return_value={
                    "error": f"{status} Client Error",
                    "detail": {"detail": "denied"},
                    "status_code": status,
                },
            ):
                result = wiki_server.download_attachment("attachment-id")
                self.assertTrue(result.isError)
                self.assertIn(str(status), result.content[0].text)

    def test_live_caller_sequence_reassembles_ranges_to_authoritative_digest(self):
        """Mirror metadata -> binary for two consecutive top-level range calls."""
        whole = b"caller-sequence"
        digest = hashlib.sha256(whole).hexdigest()
        calls = []

        def get_metadata(method, endpoint):
            calls.append(("metadata", method, endpoint))
            return metadata(whole)

        def get_range(method, endpoint, *, extra_headers, max_bytes):
            calls.append(("binary", method, endpoint, extra_headers["Range"]))
            start, end = map(
                int, extra_headers["Range"].removeprefix("bytes=").split("-")
            )
            end = min(end, len(whole) - 1)
            chunk = whole[start : end + 1]
            return {
                "content": chunk,
                "status_code": 206,
                "headers": {
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {start}-{end}/{len(whole)}",
                    "X-Wiki-Integrity": "partial-range",
                    "X-Wiki-Checksum-SHA256": digest,
                    "X-Wiki-Storage-Version": "version-1",
                },
            }

        with (
            patch.object(wiki_server.base, "api_request", side_effect=get_metadata),
            patch.object(
                wiki_server.base, "api_binary_request", side_effect=get_range
            ),
        ):
            first = wiki_server.download_attachment(
                "attachment-id", offset_bytes=0, length_bytes=6
            )
            second = wiki_server.download_attachment(
                "attachment-id", offset_bytes=6, length_bytes=len(whole) - 6
            )

        rebuilt = b"".join(
            base64.b64decode(
                next(
                    item
                    for item in result.content
                    if isinstance(item, EmbeddedResource)
                ).resource.blob
            )
            for result in (first, second)
        )
        self.assertEqual(rebuilt, whole)
        self.assertEqual(hashlib.sha256(rebuilt).hexdigest(), digest)
        self.assertEqual(
            [call[0] for call in calls],
            ["metadata", "binary", "metadata", "binary"],
        )


if __name__ == "__main__":
    unittest.main()
