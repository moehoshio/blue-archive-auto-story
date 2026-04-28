"""Optional OCR wrapper.

OCR is *not* required for the core flow – the engine decides everything via
template matching. OCR is useful for:
    * Confirming the chapter name when navigating menus.
    * Reading short status text where a template would be brittle.

Two backends are supported, selected by config:
    - ``tesseract`` (via pytesseract)  – needs a system tesseract binary.
    - ``paddle``    (via paddleocr)    – heavier, multi-language.
Both are imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float = 0.0


class OcrEngine:
    def __init__(self, backend: str = "tesseract", lang: str = "chi_tra+eng") -> None:
        self.backend = backend
        self.lang = lang
        self._impl = None

    # ---------------- backend resolution ----------------
    def _ensure(self) -> None:
        if self._impl is not None:
            return
        if self.backend == "tesseract":
            try:
                import pytesseract  # type: ignore[import-not-found]
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "pytesseract is not installed. Install with `pip install bass[ocr]`."
                ) from e
            self._impl = pytesseract
        elif self.backend == "paddle":
            try:
                from paddleocr import PaddleOCR  # type: ignore[import-not-found]
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "paddleocr is not installed. Install with `pip install bass[ocr-paddle]`."
                ) from e
            # Paddle's lang strings differ.
            paddle_lang = {"chi_tra": "chinese_cht", "chi_sim": "ch", "eng": "en", "jpn": "japan"}
            lang = paddle_lang.get(self.lang.split("+")[0], "chinese_cht")
            self._impl = PaddleOCR(use_angle_cls=False, lang=lang, show_log=False)
        else:
            raise ValueError(f"unknown OCR backend: {self.backend!r}")

    # ---------------- public API ----------------
    def read(self, image) -> OcrResult:
        """Return the recognized text from a BGR ndarray image."""
        self._ensure()
        if self.backend == "tesseract":
            import cv2  # type: ignore[import-not-found]

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            text = self._impl.image_to_string(gray, lang=self.lang)  # type: ignore[union-attr]
            return OcrResult(text=text.strip())
        # paddle
        out = self._impl.ocr(image, cls=False)  # type: ignore[union-attr]
        # Paddle returns nested structure: [[ [box, (text, conf)], ... ]]
        lines: list[str] = []
        confs: list[float] = []
        for page in out or []:
            for line in page or []:
                try:
                    txt, conf = line[1]
                    lines.append(str(txt))
                    confs.append(float(conf))
                except Exception:  # noqa: BLE001
                    continue
        avg = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(text="\n".join(lines).strip(), confidence=avg)
