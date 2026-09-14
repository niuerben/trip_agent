"""Stable domain errors for planning operations."""
from typing import Optional


class PlanningDomainError(RuntimeError):
    code = "planning_domain_error"

    def __init__(self, message: str, *, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


class ChangeExecutionError(PlanningDomainError):
    code = "change_execution_error"

    def __init__(self, message: str, *, code: Optional[str] = None, cause: Optional[BaseException] = None):
        super().__init__(message, cause=cause)
        if code:
            self.code = code

    def __str__(self) -> str:
        return self.message
