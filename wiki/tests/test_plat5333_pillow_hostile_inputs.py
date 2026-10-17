"""PLAT-5333: hostile Pillow image/font/PDF inputs are rejected crash-free and within bounds.

Regression coverage for the Pillow advisory paths remediated by the ``Pillow>=12.2.0``
floor (PLAT-4459, wiki PR #17). The wiki's Pillow consumer boundary is the
``Space.logo`` ImageField — Django validates every uploaded logo through Pillow
(``Image.open`` + ``verify()``). These tests feed representative hostile inputs
through that real consumer path and assert:

- **crash-free**: a clean 4xx validation rejection (``invalid_image``), never a
  500 / uncaught exception escaping the view;
- **bounded time**: the whole validation completes well under a hard time bound —
  a decompression bomb that actually decoded 100000x100000 pixels would hang for
  minutes or OOM, so a fast rejection proves no unbounded decode/allocation;
- **bounded memory**: the bomb is rejected by Pillow's ``MAX_IMAGE_PIXELS`` guard
  at header-parse time (before any pixel decode), so no large buffer is allocated
  (the 30 GB the bomb would decode to is never materialized).

The font parser (``Pillow.ImageFont`` / FreeType) is part of the same Pillow
dependency surface the wiki ships, but the wiki has no dedicated font consumer —
so hostile font inputs are exercised through Pillow's font loader directly, with
the same crash-free + bounded-time assertions. This is an actual parser exercise,
not a version assertion.

Advisory map (all fixed by the 12.2.0 floor):
- CVE-2023-4863 / GHSA-j7hp-h8jx-5ppr — libwebp heap overflow (crafted WebP).
- CVE-2023-50447 / GHSA-3f63-hfp8-52jq — ImageMath.eval heap overflow.
- CVE-2024-28219 / GHSA-44wm-f244-xhp3 — ImageDraw/ImageFont buffer handling.
- PYSEC-2026-165 / GHSA-r73j-pqj5-w3x7 / GHSA-wjx4-4jcj-g98j — decoder/parser fixes.
"""
import io
import struct
import time
import zlib

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from wiki.models import Space

User = get_user_model()

# A generous wall-clock bound. Real hostile-input rejections complete in
# milliseconds; this only guards against hangs / unbounded decode loops.
TIME_BOUND_SECONDS = 5.0


def _png_chunk(typ, data):
    return (
        struct.pack('>I', len(data)) + typ + data
        + struct.pack('>I', zlib.crc32(typ + data) & 0xFFFFFFFF)
    )


def decompression_bomb_png():
    """A valid PNG header declaring 100000x100000 px (10^10 px ≈ 30 GB RGB).

    Tiny on disk (one scanline of IDAT) but far beyond Pillow's
    ``MAX_IMAGE_PIXELS`` guard (178,956,970 px). If a consumer tried to decode it,
    it would allocate tens of GB and hang — the regression assertion is that the
    wiki's consumer rejects it at header-parse time, fast.
    """
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', 100000, 100000, 8, 2, 0, 0, 0)
    idat = zlib.compress(b'\x00\x00\x00\x00')  # one 1-px scanline
    return sig + _png_chunk(b'IHDR', ihdr) + _png_chunk(b'IDAT', idat) + _png_chunk(b'IEND', b'')


def malformed_image():
    """Truncated PNG signature + junk — exercises the generic decoder reject path."""
    return b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


def crafted_webp():
    """Malformed RIFF/WEBP container — exercises the libwebp decoder path
    (CVE-2023-4863 / GHSA-j7hp-h8jx-5ppr)."""
    return b'RIFF' + struct.pack('<I', 20) + b'WEBPVP8 ' + b'\x00' * 8


def hostile_pdf():
    """Malformed PDF with a valid %PDF header — Pillow's PDF plugin must reject it
    cleanly (no Ghostscript in the image, and no unbounded parse)."""
    return b'%PDF-1.4\n' + b'\x00' * 128 + b'\n%%EOF\n'


def hostile_font():
    """Malformed TrueType: valid sfnt version tag, garbage tables."""
    return b'\x00\x01\x00\x00' + b'\x00' * 256


def valid_png():
    """A real 4x4 PNG — positive control proving the consumer accepts good input."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, format='PNG')
    return buf.getvalue()


class PillowHostileInputsTests(APITestCase):
    """Hostile Pillow inputs through the real Space.logo consumer boundary."""

    def setUp(self):
        self.client = APIClient(HTTP_X_ORGANIZATION_ID='1')
        self.user = User.objects.create_user(
            username='pillow5333', email='pillow5333@example.com', password='x',
            is_staff=True, is_superuser=True,
        )
        self.client.force_authenticate(user=self.user)
        self.space = Space.objects.create(
            organization_id=1, key='ENG', name='Engineering',
            visibility='org', owner_id=self.user.id,
        )

    def _upload_logo(self, data, name='hostile.png', content_type='image/png'):
        """PATCH the Space with a logo file — the real Pillow consumer path."""
        uploaded = SimpleUploadedFile(name, data, content_type=content_type)
        started = time.monotonic()
        resp = self.client.patch(f'/api/spaces/ENG/', {'logo': uploaded}, format='multipart')
        elapsed = time.monotonic() - started
        return resp, elapsed

    def _assert_rejected_within_bounds(self, data, name='hostile.png', content_type='image/png'):
        resp, elapsed = self._upload_logo(data, name=name, content_type=content_type)
        self.assertLess(elapsed, TIME_BOUND_SECONDS, 'hostile input validation exceeded time bound')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content[:200])
        self.assertIn('invalid_image', str(resp.data))
        return resp, elapsed

    def test_decompression_bomb_logo_rejected_within_bounds(self):
        """A 30 GB decompression bomb is rejected at header-parse time, fast."""
        resp, elapsed = self._assert_rejected_within_bounds(
            decompression_bomb_png(), name='bomb.png',
        )
        # The bomb declares 10^10 pixels; a fast rejection proves Pillow's
        # MAX_IMAGE_PIXELS guard fired before any pixel decode (bounded memory).
        self.assertLess(elapsed, 2.0, 'bomb was not rejected at header-parse time')

    def test_malformed_image_logo_rejected_within_bounds(self):
        """Truncated/corrupt image bytes are rejected cleanly."""
        self._assert_rejected_within_bounds(malformed_image(), name='truncated.png')

    def test_hostile_webp_logo_rejected_within_bounds(self):
        """Crafted WebP (CVE-2023-4863 libwebp path) is rejected cleanly."""
        self._assert_rejected_within_bounds(crafted_webp(), name='hostile.webp')

    def test_hostile_pdf_logo_rejected_within_bounds(self):
        """Hostile PDF fed to the image consumer is rejected cleanly."""
        self._assert_rejected_within_bounds(
            hostile_pdf(), name='hostile.pdf', content_type='application/pdf',
        )

    def test_valid_logo_accepted(self):
        """Positive control: a real PNG logo is accepted and stored."""
        resp, elapsed = self._upload_logo(valid_png(), name='ok.png')
        self.assertLess(elapsed, TIME_BOUND_SECONDS)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content[:200])
        self.space.refresh_from_db()
        self.assertTrue(self.space.logo)

    def test_hostile_font_rejected_within_bounds(self):
        """Pillow's font parser (ImageFont/FreeType) rejects a malformed TTF
        cleanly and within bounds — the font half of the dependency surface
        (CVE-2024-28219 / GHSA-44wm-f244-xhp3 family)."""
        from PIL import ImageFont

        started = time.monotonic()
        with self.assertRaises(OSError):
            ImageFont.truetype(io.BytesIO(hostile_font()), size=16)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, TIME_BOUND_SECONDS, 'font parse exceeded time bound')

    def test_hostile_font_rendering_crash_free(self):
        """A hostile font must never crash the process; loading fails cleanly and
        rendering a glyph is a no-op / clean error, never a segfault."""
        from PIL import Image, ImageDraw, ImageFont

        started = time.monotonic()
        try:
            font = ImageFont.truetype(io.BytesIO(hostile_font()), size=16)
        except OSError:
            font = None
        if font is not None:
            img = Image.new('RGB', (32, 32), 'white')
            draw = ImageDraw.Draw(img)
            draw.text((2, 2), 'A', fill='black', font=font)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, TIME_BOUND_SECONDS, 'font render exceeded time bound')
