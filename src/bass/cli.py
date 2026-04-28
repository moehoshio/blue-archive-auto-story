"""``bass`` command-line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import load_config, load_tasks
from .utils.logging import configure, log


@click.group(help="Blue Archive Auto Story (bass)")
@click.version_option(__version__)
@click.option("--log-level", default="INFO", show_default=True, help="DEBUG / INFO / WARNING / ERROR")
def cli(log_level: str) -> None:
    configure(level=log_level.upper())


# ---------------------------------------------------------------------------
# `bass devices`
# ---------------------------------------------------------------------------


@cli.command("devices", help="List ADB devices visible to bass.")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5037, show_default=True, type=int)
def devices_cmd(host: str, port: int) -> None:
    from .device.adb_client import AdbClient

    infos = AdbClient.list_devices(host=host, port=port)
    if not infos:
        click.echo("No devices found. Is `adb start-server` running?")
        sys.exit(1)
    click.echo(f"{'SERIAL':<28} {'STATE':<10} {'RESOLUTION':<12} MODEL")
    for info in infos:
        res = f"{info.width}x{info.height}" if info.width else "?"
        click.echo(f"{info.serial:<28} {info.state:<10} {res:<12} {info.model}")


# ---------------------------------------------------------------------------
# `bass screenshot`
# ---------------------------------------------------------------------------


@cli.command("screenshot", help="Capture a screenshot from the device and save it as PNG.")
@click.option("--config", "-c", "config_path", default="configs/config.yaml", show_default=True)
@click.option("--output", "-o", default="screenshot.png", show_default=True)
def screenshot_cmd(config_path: str, output: str) -> None:
    from .device.adb_client import AdbClient

    cfg = load_config(config_path)
    client = AdbClient(serial=cfg.adb.serial, host=cfg.adb.host, port=cfg.adb.port)
    data = client.screencap_png()
    Path(output).write_bytes(data)
    click.echo(f"saved {len(data)} bytes -> {output}")


# ---------------------------------------------------------------------------
# `bass run`
# ---------------------------------------------------------------------------


@cli.command("run", help="Run automated tasks from tasks.yaml.")
@click.option("--config", "-c", "config_path", default="configs/config.yaml", show_default=True)
@click.option("--tasks", "-t", "tasks_path", default="configs/tasks.yaml", show_default=True)
@click.option(
    "--templates", default="assets/templates", show_default=True, help="Templates root directory."
)
@click.option("--regions", default="assets/regions.yaml", show_default=True)
def run_cmd(config_path: str, tasks_path: str, templates: str, regions: str) -> None:
    from .device.adb_client import AdbClient
    from .engine.scheduler import Scheduler
    from .engine.state_machine import EngineConfig, StateMachine
    from .vision.matcher import TemplateMatcher, load_regions
    from .vision.state_detector import StateDetector

    cfg = load_config(config_path)
    task_file = load_tasks(tasks_path)

    client = AdbClient(serial=cfg.adb.serial, host=cfg.adb.host, port=cfg.adb.port)
    dev_w, dev_h = client.resolution()
    log.info(f"device resolution: {dev_w}x{dev_h}")

    region_cfg = load_regions(regions)
    matcher = TemplateMatcher(
        templates_root=templates,
        regions=region_cfg,
        scales=cfg.match_scales,
        base_resolution=(cfg.base_resolution.width, cfg.base_resolution.height),
        device_resolution=(dev_w, dev_h),
        language=cfg.language,
    )
    detector = StateDetector(matcher)

    machine = StateMachine(
        device=client,
        detector=detector,
        config=EngineConfig(
            loop_interval_ms=cfg.loop_interval_ms,
            unknown_scene_limit=cfg.unknown_scene_limit,
            chapter_timeout_sec=cfg.chapter_timeout_sec,
            screenshots_on_unknown=cfg.screenshots_on_unknown,
            debug_dump_dir=cfg.debug_dump_dir,
        ),
    )
    sched = Scheduler(
        machine=machine,
        task_file=task_file,
        global_timeout_sec=cfg.global_timeout_sec,
        chapter_timeout_sec=cfg.chapter_timeout_sec,
    )
    records = sched.run()
    failed = sum(1 for r in records if r.status.name == "FAILED")
    click.echo(f"completed: {len(records) - failed}/{len(records)} ok, {failed} failed")
    sys.exit(0 if failed == 0 else 2)


# ---------------------------------------------------------------------------
# `bass capture`
# ---------------------------------------------------------------------------


@cli.command("capture", help="Capture and crop a template image from the current screen.")
@click.option("--config", "-c", "config_path", default="configs/config.yaml", show_default=True)
@click.option("--name", "-n", required=True, help="Template name like 'battle/sortie'.")
@click.option("--templates", default="assets/templates", show_default=True)
@click.option(
    "--roi",
    default=None,
    help="Crop ROI 'x,y,w,h' in device pixels. Omit to save the whole screen.",
)
def capture_cmd(config_path: str, name: str, templates: str, roi: str | None) -> None:
    from .device.adb_client import AdbClient
    from .vision.capture import save_image

    cfg = load_config(config_path)
    client = AdbClient(serial=cfg.adb.serial, host=cfg.adb.host, port=cfg.adb.port)
    img = client.screencap_ndarray()
    if roi:
        try:
            x, y, w, h = (int(p.strip()) for p in roi.split(","))
        except Exception as exc:
            raise click.BadParameter(f"invalid --roi: {roi!r}") from exc
        img = img[y : y + h, x : x + w]
    out = Path(templates) / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    save_image(str(out), img)
    click.echo(f"saved template -> {out}")


# ---------------------------------------------------------------------------
# `bass replay`
# ---------------------------------------------------------------------------


@cli.command("replay", help="Run the state detector against a folder of screenshots.")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--config", "-c", "config_path", default="configs/config.yaml", show_default=True)
@click.option("--templates", default="assets/templates", show_default=True)
@click.option("--regions", default="assets/regions.yaml", show_default=True)
def replay_cmd(folder: str, config_path: str, templates: str, regions: str) -> None:
    from .vision.capture import load_image
    from .vision.matcher import TemplateMatcher
    from .vision.matcher import load_regions as _load_regions
    from .vision.state_detector import StateDetector

    cfg = load_config(config_path)
    region_cfg = _load_regions(regions)
    matcher = TemplateMatcher(
        templates_root=templates,
        regions=region_cfg,
        scales=cfg.match_scales,
        base_resolution=(cfg.base_resolution.width, cfg.base_resolution.height),
        device_resolution=(cfg.base_resolution.width, cfg.base_resolution.height),
        language=cfg.language,
    )
    detector = StateDetector(matcher)
    p = Path(folder)
    files = sorted(p.glob("*.png"))
    for f in files:
        img = load_image(str(f))
        obs = detector.detect(img)
        click.echo(f"{f.name}\t{obs.state}")


def main() -> None:  # pragma: no cover – CLI entry point
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
