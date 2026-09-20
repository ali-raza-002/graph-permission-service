from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from warden.dsl.ast import SourcePos


class DslIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    line: int
    column: int
    end_line: int
    end_column: int
    severity: Literal["error", "warning"] = "error"

    @classmethod
    def at(
        cls,
        code: str,
        message: str,
        pos: SourcePos | None,
        length: int = 1,
        *,
        severity: Literal["error", "warning"] = "error",
    ) -> DslIssue:
        line, column = (pos.line, pos.column) if pos else (1, 1)
        return cls(
            code=code,
            message=message,
            line=line,
            column=column,
            end_line=line,
            end_column=column + max(length, 1),
            severity=severity,
        )

    def __str__(self) -> str:
        return f"{self.line}:{self.column} {self.message}"


class ModelCompileError(Exception):
    def __init__(self, issues: list[DslIssue]) -> None:
        self.issues = issues
        summary = "; ".join(str(issue) for issue in issues[:3])
        super().__init__(f"authorization model is invalid: {summary}")
