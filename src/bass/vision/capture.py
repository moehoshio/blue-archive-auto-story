"""Helpers for converting raw screen captures into ndarray frames."""

from __future__ import annotations


def bytes_to_ndarray(png_or_jpeg_bytes: bytes):  # -> np.ndarray (BGR)
    """Decode a PNG/JPEG byte-string to an OpenCV BGR ndarray."""
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    arr = np.frombuffer(png_or_jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image bytes")
    return img


def load_image(path: str):  # -> np.ndarray (BGR)
    import cv2  # type: ignore[import-not-found]

    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"could not read image: {path}")
    return img


def save_image(path: str, img) -> None:
    import cv2  # type: ignore[import-not-found]

    if not cv2.imwrite(path, img):
        raise RuntimeError(f"failed to write image to {path}")
