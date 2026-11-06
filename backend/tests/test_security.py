import io
import socket
import tempfile
import unittest
from pathlib import Path

from app.security import copy_limited, safe_upload_name, validate_public_url


class InputSecurityTests(unittest.TestCase):
    def test_upload_filename_cannot_escape_upload_directory(self):
        self.assertEqual(safe_upload_name("../../secret.txt"), "secret.txt")
        self.assertEqual(safe_upload_name(r"C:\\temp\\notes.md"), "notes.md")

    def test_upload_size_limit_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "upload.bin"
            with self.assertRaisesRegex(ValueError, "不能超过"):
                copy_limited(io.BytesIO(b"12345"), destination, limit=4)
            self.assertFalse(destination.exists())

    def test_private_web_destinations_are_blocked(self):
        for url in (
            "http://127.0.0.1/admin",
            "http://localhost:8787/api/stats",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_url(url)

    def test_domain_resolving_to_private_ip_is_blocked(self):
        def private_resolver(*_args):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 80))]

        with self.assertRaises(ValueError):
            validate_public_url("https://example.test/page", private_resolver)

    def test_public_destination_is_allowed(self):
        def public_resolver(*_args):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

        self.assertEqual(
            validate_public_url("https://example.com/page", public_resolver),
            "https://example.com/page",
        )


if __name__ == "__main__":
    unittest.main()
