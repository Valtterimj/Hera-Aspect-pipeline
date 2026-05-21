
from dataclasses import dataclass
from typing import Optional

def format_exeption_chain(e: BaseException) -> str:
    parts = [str(e)]
    cause = e.__cause__
    while cause is not None:
        parts.append(str(cause))
        cause = cause.__cause__
    return " | caused by: ".join(parts)

class PipelineError(Exception):
    "Base class for all pipeline-raised errors"
    def __init__(
            self,
            message: str,
            channel: Optional[str] = None,
            level: Optional[str] = None,
            stage: Optional[str] = None,
            path: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.channel = channel
        self.level = level
        self.stage = stage
        self.path = path
    
    def context_str(self) -> str:
        parts = []
        if self.channel:
            parts.append(f"channel={self.channel}")
        if self.level:
            parts.append(f"level={self.level}")
        if self.stage:
            parts.append(f"stage={self.stage}")
        if self.path:
            parts.append(f"path={self.path}")
        return ", ".join(parts)

    def __str__(self) -> str:
        ctx = self.context_str()
        return f"{self.message}" + (f" ({ctx})" if ctx else "")
    
class ConfigError(PipelineError):
    "Raised when the congif is missing or failed to load"

class ValidationError(PipelineError):
    "Raised when validation fails"

class CalibrationError(PipelineError):
    "Raised when calibration fails"