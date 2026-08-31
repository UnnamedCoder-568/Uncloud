from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "completed", "failed"]


@dataclass
class Task:
    id: str
    description: str
    tool_id: str
    args: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    status: TaskStatus = "pending"
    output: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "description": self.description, "tool_id": self.tool_id,
            "args": self.args, "dependencies": self.dependencies, "status": self.status,
            "output": self.output, "error": self.error,
        }


@dataclass
class ExecutionGraph:
    goal: str
    tasks: dict[str, Task] = field(default_factory=dict)
    start_node_ids: list[str] = field(default_factory=list)

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def ready_tasks(self) -> list[Task]:
        return [
            t for t in self.tasks.values()
            if t.status == "pending"
            and all(self.tasks.get(dep, Task(id=dep, description="", tool_id="")).status == "completed"
                    for dep in t.dependencies)
        ]

    def all_terminal(self) -> bool:
        return all(t.status in ("completed", "failed") for t in self.tasks.values())

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "start_node_ids": self.start_node_ids,
        }
