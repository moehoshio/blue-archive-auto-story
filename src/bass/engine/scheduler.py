"""Scheduler: turns a ``tasks.yaml`` into a sequence of state-machine runs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ..flows.battle_flow import BattleFlow
from ..flows.event_flow import EventFlow, EventFlowState
from ..flows.story_flow import StoryFlow
from ..utils.logging import log
from ..vision.state_detector import SceneObservation, SceneState

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Task, TaskFile
    from .state_machine import StateMachine


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class TaskRecord:
    task: Task
    status: TaskStatus = TaskStatus.PENDING
    error: str = ""
    duration_sec: float = 0.0


@dataclass
class Scheduler:
    """Drives one task at a time via the StateMachine."""

    machine: StateMachine
    task_file: TaskFile
    global_timeout_sec: int = 7200
    chapter_timeout_sec: int = 1800
    records: list[TaskRecord] = field(default_factory=list)

    def run(self) -> list[TaskRecord]:
        """Execute every task. Returns a per-task record list."""
        deadline = time.monotonic() + self.global_timeout_sec
        for task in self.task_file.tasks:
            rec = TaskRecord(task=task, status=TaskStatus.RUNNING)
            self.records.append(rec)

            if time.monotonic() > deadline:
                rec.status = TaskStatus.SKIPPED
                rec.error = "global timeout reached"
                log.warning(f"skipping task {task!r}: global timeout")
                continue

            t0 = time.monotonic()
            try:
                self._run_task(task)
                rec.status = TaskStatus.DONE
            except Exception as exc:  # noqa: BLE001
                log.exception(f"task {task!r} failed: {exc!r}")
                rec.status = TaskStatus.FAILED
                rec.error = repr(exc)
            finally:
                rec.duration_sec = time.monotonic() - t0
                log.info(
                    f"task done: type={task.type} status={rec.status} duration={rec.duration_sec:.1f}s"
                )
        return self.records

    # ------------------------------------------------------------------
    def _run_task(self, task: Task) -> None:
        defaults = self.task_file.defaults
        story = StoryFlow(defaults.story)
        battle = BattleFlow(defaults.battle)
        event = EventFlow()

        if task.type == "story_only":
            self._run_story_until_list(story, battle)
            return

        if task.type == "main_story":
            log.info(f"main_story volume={task.volume} chapter={task.chapter}")
            self._run_story_until_list(story, battle)
            return

        if task.type == "event":
            if not task.id:
                raise ValueError("event task missing 'id'")
            state = EventFlowState(event_id=task.id, chapters=task.chapters)
            log.info(f"event id={state.event_id} chapters={state.chapters}")
            # Step 1: navigate to event entry from HOME (best effort).
            self.machine.run_flows(
                [event],
                is_done=lambda obs: EventFlow.is_in_chapter(obs),
                max_seconds=self.chapter_timeout_sec,
            )
            # Step 2: run as many chapters as configured.
            for _ in state.chapters:
                self._run_story_until_list(story, battle)
                state.advance()
            return

        raise ValueError(f"unknown task type: {task.type!r}")

    # ------------------------------------------------------------------
    def _run_story_until_list(self, story: StoryFlow, battle: BattleFlow) -> SceneObservation:
        """Drive Story+Battle flows until we see STORY_LIST or HOME."""

        def is_done(obs: SceneObservation) -> bool:
            return obs.state in (SceneState.STORY_LIST, SceneState.HOME)

        return self.machine.run_flows(
            [story, battle],
            is_done=is_done,
            max_seconds=self.chapter_timeout_sec,
        )
