"""Validation layer for the agent pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    issues: tuple[Any, ...] = field(default_factory=tuple)
    raw: Any = None

    def __bool__(self) -> bool:
        return self.passed

    def as_observation(self) -> dict[str, Any]:
        return {"passed": self.passed, "issues": list(self.issues)}


class ValidateAgent:
    def __init__(self, validator: Optional[Callable[[Any], Any]] = None) -> None:
        self.validator = validator
        self.last_result = ValidationResult(False, raw=None)

    def validate(self, prompt: Any) -> bool:
        try:
            raw = self.validator(prompt) if self.validator else prompt
            self.last_result = self._normalise(raw)
        except Exception as error:
            self.last_result = ValidationResult(
                False,
                issues=(f"{type(error).__name__}: {error}",),
                raw=error,
            )
        return self.last_result.passed

    @staticmethod
    def _normalise(raw: Any) -> ValidationResult:
        if isinstance(raw, ValidationResult):
            return raw
        if isinstance(raw, bool):
            return ValidationResult(raw, raw=raw)
        if isinstance(raw, str):
            try:
                return ValidateAgent._normalise(json.loads(raw))
            except json.JSONDecodeError:
                return ValidationResult(bool(raw.strip()), raw=raw)
        if isinstance(raw, dict):
            passed = bool(raw.get("passed", raw.get("valid", False)))
            issues = raw.get("issues") or raw.get("errors") or []
            if not isinstance(issues, (list, tuple)):
                issues = [issues]
            return ValidationResult(passed, tuple(issues), raw=raw)
        return ValidationResult(bool(raw), raw=raw)


def validate(prompt: Any, validator: Optional[Callable[[Any], Any]] = None) -> bool:
    return ValidateAgent(validator=validator).validate(prompt)

