"""YAML task config loader for the heartbeat daemon.

Parses `tasks.yaml` into a list of immutable `TaskConfig` records, expands
environment references in path/command fields, and rejects unknown keys,
invalid cron expressions, unknown timezones, and missing fields.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from croniter import croniter

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
VALID_TYPES = {"pi_workflow", "shell"}
VALID_CATCHUP = {"all", "one", "none"}
TASK_KEYS = {
    "name",
    "cron",
    "cron_tz",
    "catchup",
    "precondition",
    "depends_on",
    "type",
    "workflow",
    "prompt",
    "command",
    "timeout_seconds",
}
DEFAULT_TIMEOUT_SECONDS = 3600


@dataclass(frozen=True)
class TaskConfig:
    name: str
    cron: str
    type: str
    cron_tz: str = "UTC"
    catchup: str = "one"
    precondition: str | None = None
    depends_on: tuple[str, ...] = ()
    workflow: str | None = None
    prompt: str | None = None
    command: tuple[str, ...] | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class ConfigError(ValueError):
    """Raised when tasks.yaml is malformed."""


def _expand_env_refs(value: str, *, task_name: str, key: str) -> str:
    missing = sorted(
        {
            name
            for match in ENV_RE.finditer(value)
            for name in (match.group(1) or match.group(2),)
            if name not in os.environ
        }
    )
    if missing:
        raise ConfigError(f"task {task_name}: {key} references unset env vars {missing}")
    return os.path.expanduser(os.path.expandvars(value))


def _validate_task(raw: Any) -> TaskConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"task entry must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - TASK_KEYS
    if unknown:
        raise ConfigError(f"task has unknown keys: {sorted(unknown)}")

    for required in ("name", "cron", "type"):
        if required not in raw:
            raise ConfigError(f"task missing required key: {required!r}")

    name = raw["name"]
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError(f"invalid task name: {name!r} (expected [a-z0-9][a-z0-9-]*)")

    cron = raw["cron"]
    if not isinstance(cron, str) or not croniter.is_valid(cron):
        raise ConfigError(f"task {name}: invalid cron expression {cron!r}")

    cron_tz = raw.get("cron_tz", "UTC")
    if not isinstance(cron_tz, str):
        raise ConfigError(f"task {name}: cron_tz must be a string")
    try:
        ZoneInfo(cron_tz)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"task {name}: unknown cron_tz {cron_tz!r}") from exc

    catchup = raw.get("catchup", "one")
    if catchup not in VALID_CATCHUP:
        raise ConfigError(f"task {name}: invalid catchup {catchup!r}")

    type_ = raw["type"]
    if type_ not in VALID_TYPES:
        raise ConfigError(f"task {name}: invalid type {type_!r}")

    workflow = raw.get("workflow")
    prompt = raw.get("prompt")
    command = raw.get("command")

    if type_ == "pi_workflow":
        if not isinstance(workflow, str) or not workflow.strip():
            raise ConfigError(f"task {name}: pi_workflow requires non-empty 'workflow' path")
        workflow = _expand_env_refs(workflow, task_name=name, key="workflow")
        if not workflow.strip():
            raise ConfigError(f"task {name}: pi_workflow requires non-empty 'workflow' path")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ConfigError(f"task {name}: pi_workflow requires non-empty 'prompt'")
        if command is not None:
            raise ConfigError(f"task {name}: pi_workflow must not set 'command'")
        command_t: tuple[str, ...] | None = None
    else:
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            raise ConfigError(f"task {name}: shell requires non-empty 'command' list of strings")
        if workflow is not None or prompt is not None:
            raise ConfigError(f"task {name}: shell must not set 'workflow' or 'prompt'")
        workflow = None
        prompt = None
        command_t = tuple(_expand_env_refs(c, task_name=name, key="command") for c in command)

    precondition = raw.get("precondition")
    if precondition is not None and (not isinstance(precondition, str) or not precondition.strip()):
        raise ConfigError(f"task {name}: precondition must be a non-empty string")
    if precondition is not None:
        precondition = _expand_env_refs(precondition, task_name=name, key="precondition")

    depends_on_raw = raw.get("depends_on", [])
    if not isinstance(depends_on_raw, list) or not all(isinstance(d, str) and d.strip() for d in depends_on_raw):
        raise ConfigError(f"task {name}: depends_on must be a list of task names")
    depends_on = tuple(depends_on_raw)

    timeout_seconds = raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ConfigError(f"task {name}: timeout_seconds must be a positive int")

    return TaskConfig(
        name=name,
        cron=cron,
        type=type_,
        cron_tz=cron_tz,
        catchup=catchup,
        precondition=precondition,
        depends_on=depends_on,
        workflow=workflow,
        prompt=prompt,
        command=command_t,
        timeout_seconds=timeout_seconds,
    )


def load_tasks(path: Path) -> list[TaskConfig]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ConfigError(f"{path}: root must be a mapping")
    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ConfigError(f"{path}: 'tasks' must be a non-empty list")

    tasks = [_validate_task(t) for t in tasks_raw]
    names = [t.name for t in tasks]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"{path}: duplicate task names {sorted(duplicates)}")
    name_set = set(names)
    unknown_deps = {dep for task in tasks for dep in task.depends_on if dep not in name_set}
    if unknown_deps:
        raise ConfigError(f"{path}: unknown depends_on task names {sorted(unknown_deps)}")
    return tasks
