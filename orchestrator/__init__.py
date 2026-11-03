"""Оркестратор и память проекта."""

__all__ = ["Orchestrator", "ProjectMemory"]


def __getattr__(name: str):
    if name == "Orchestrator":
        from .orchestrator import Orchestrator

        return Orchestrator
    if name == "ProjectMemory":
        from .memory import ProjectMemory

        return ProjectMemory
    raise AttributeError(name)
