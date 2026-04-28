"""Vision sub-package: capture, template matching, scene detection, OCR."""

from .capture import bytes_to_ndarray
from .matcher import MatchResult, TemplateMatcher, load_regions
from .state_detector import SceneState, StateDetector

__all__ = [
    "bytes_to_ndarray",
    "MatchResult",
    "TemplateMatcher",
    "load_regions",
    "SceneState",
    "StateDetector",
]
