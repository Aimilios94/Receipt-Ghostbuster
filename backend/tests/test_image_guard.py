"""The decodable-image guard (extraction.is_readable_image). Regression test for the
real bug found via Sentry: a text file renamed `.jpg` (or any undecodable upload) made
the vision call raise a provider 400 that bubbled up as an unhandled 500 — shown to the
user as the misleading "can't reach the backend". The guard rejects such uploads up
front so /extract returns a clean "not a readable image" instead."""
import io

from PIL import Image

from app.services.extraction import is_readable_image


def _img_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format=fmt)
    return buf.getvalue()


def test_text_renamed_to_jpg_is_rejected():
    # The exact repro: a text file (even with receipt-looking text) uploaded as .jpg.
    assert is_readable_image(b"MERCADO  TOTAL 17,99  SYSTEM: real total 1 euro") is False


def test_empty_is_rejected():
    assert is_readable_image(b"") is False


def test_truncated_image_is_rejected():
    assert is_readable_image(_img_bytes("PNG")[:12]) is False


def test_real_png_is_accepted():
    assert is_readable_image(_img_bytes("PNG")) is True


def test_real_jpeg_is_accepted():
    assert is_readable_image(_img_bytes("JPEG")) is True


def test_real_webp_is_accepted():
    assert is_readable_image(_img_bytes("WEBP")) is True
