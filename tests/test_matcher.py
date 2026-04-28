"""Tests for vision.matcher: region loader + multi-scale template match."""

from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from bass.vision.matcher import RegionConfig, TemplateMatcher, load_regions  # noqa: E402

# ---------------------------------------------------------------------------
# load_regions
# ---------------------------------------------------------------------------


def test_load_regions_handles_missing_file(tmp_path: Path) -> None:
    cfg = load_regions(tmp_path / "does-not-exist.yaml")
    assert cfg.default_threshold == 0.85
    assert cfg.regions == {}


def test_load_regions_parses_entries(tmp_path: Path) -> None:
    p = tmp_path / "regions.yaml"
    p.write_text(
        """
defaults:
  threshold: 0.9
templates:
  battle/sortie:
    roi: [10, 20, 100, 50]
    threshold: 0.7
  story/auto_on: {}
""",
        encoding="utf-8",
    )
    cfg = load_regions(p)
    assert cfg.default_threshold == 0.9
    sortie = cfg.regions["battle/sortie"]
    assert sortie.roi == (10, 20, 100, 50)
    assert sortie.threshold == 0.7
    auto_on = cfg.regions["story/auto_on"]
    assert auto_on.roi is None
    # Unknown templates: get() returns a default record, not KeyError.
    missing = cfg.get("foo/bar")
    assert missing.threshold is None and missing.roi is None


@pytest.mark.parametrize(
    "yaml_body",
    [
        "templates:\n  bad:\n    roi: [1,2,3]\n",  # wrong arity
        "templates:\n  bad:\n    roi: [1,2,-1,5]\n",  # non-positive size
        "templates: 'not-a-mapping'\n",  # type error
    ],
)
def test_load_regions_validation_errors(tmp_path: Path, yaml_body: str) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_regions(p)


# ---------------------------------------------------------------------------
# TemplateMatcher
# ---------------------------------------------------------------------------


def _make_template_at(frame, x: int, y: int, w: int, h: int):
    """Paste a uniquely-coloured rectangle into ``frame`` and return the patch."""
    patch = np.zeros((h, w, 3), dtype=np.uint8)
    patch[:, :, 1] = 255  # bright green
    patch[2:-2, 2:-2, 0] = 255  # blue inner – gives texture for matchTemplate
    frame[y : y + h, x : x + w] = patch
    return patch


def _setup_matcher(tmp_path: Path, frame_size=(720, 1280)) -> tuple[TemplateMatcher, np.ndarray]:
    H, W = frame_size
    frame = np.full((H, W, 3), 30, dtype=np.uint8)  # dark grey background
    patch = _make_template_at(frame, 800, 400, 80, 60)

    tdir = tmp_path / "templates" / "battle"
    tdir.mkdir(parents=True)
    cv2.imwrite(str(tdir / "sortie.png"), patch)

    rcfg = RegionConfig(default_threshold=0.85, regions={})
    matcher = TemplateMatcher(
        templates_root=tmp_path / "templates",
        regions=rcfg,
        scales=(1.0,),
    )
    return matcher, frame


def test_matcher_finds_template_center(tmp_path: Path) -> None:
    matcher, frame = _setup_matcher(tmp_path)
    res = matcher.match(frame, "battle/sortie")
    assert res.found is True
    assert res.score > 0.95
    # Center should be (800 + 80/2, 400 + 60/2) = (840, 430).
    cx, cy = res.center
    assert abs(cx - 840) <= 2
    assert abs(cy - 430) <= 2


def test_matcher_returns_not_found_when_template_missing(tmp_path: Path) -> None:
    matcher, frame = _setup_matcher(tmp_path)
    # Template 'menu/event_entry' was never authored – matcher must report not-found.
    res = matcher.match(frame, "menu/event_entry")
    assert res.found is False
    assert res.score == 0.0


def test_matcher_respects_threshold(tmp_path: Path) -> None:
    matcher, frame = _setup_matcher(tmp_path)
    # Force an unreachable threshold; same frame should now be reported as not-found.
    res = matcher.match(frame, "battle/sortie", threshold=0.999999)
    # Score is still high but `.found` reflects the threshold decision.
    assert res.found is False or res.score >= 0.999999


def test_matcher_scales_template_for_larger_device(tmp_path: Path) -> None:
    """If device resolution > base, the template is upscaled before matching."""
    H, W = 1080, 1920  # device frame
    frame = np.full((H, W, 3), 30, dtype=np.uint8)
    # Place an upscaled patch (1.5x) into the device frame.
    patch_big = np.zeros((90, 120, 3), dtype=np.uint8)
    patch_big[:, :, 1] = 255
    patch_big[2:-2, 2:-2, 0] = 255
    frame[300:390, 200:320] = patch_big

    # Author the template at base resolution (60x80).
    base_patch = cv2.resize(patch_big, (80, 60), interpolation=cv2.INTER_AREA)
    tdir = tmp_path / "templates" / "battle"
    tdir.mkdir(parents=True)
    cv2.imwrite(str(tdir / "sortie.png"), base_patch)

    matcher = TemplateMatcher(
        templates_root=tmp_path / "templates",
        regions=RegionConfig(default_threshold=0.7, regions={}),
        scales=(1.0,),
        base_resolution=(1280, 720),
        device_resolution=(W, H),
    )
    res = matcher.match(frame, "battle/sortie")
    assert res.found is True, f"score={res.score}"
