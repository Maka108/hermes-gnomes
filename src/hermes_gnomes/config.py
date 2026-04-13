"""Runtime configuration loader for Hermes Gnomes."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class QuietHours(BaseModel):
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class RateLimit(BaseModel):
    per_minute: int = Field(gt=0)
    per_day: int = Field(gt=0)


class LLMConfig(BaseModel):
    primary: str
    fallbacks: list[str] = Field(default_factory=list)


class Paths(BaseModel):
    data_dir: str
    memory_dir: str
    skills_dir: str
    sessions_dir: str


ApprovalMode = Literal["cautious", "balanced", "permissive"]


class Config(BaseModel):
    business_name: str
    timezone: str
    quiet_hours: QuietHours
    default_post_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    weekly_report_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    weekly_report_day: str
    approval_mode: ApprovalMode
    rate_limits: dict[str, RateLimit]
    approval_repings_hours: list[int]
    anomaly_baseline_days: int = Field(gt=0)
    anomaly_multiplier: float = Field(gt=1.0)
    llm: LLMConfig
    paths: Paths

    def rate_limit_for(self, tool_name: str) -> RateLimit:
        """Return the rate limit for a tool, falling back to 'default'."""
        if tool_name in self.rate_limits:
            return self.rate_limits[tool_name]
        if "default" not in self.rate_limits:
            raise KeyError("rate_limits.default must be defined in config")
        return self.rate_limits["default"]


class ConfigError(RuntimeError):
    """Raised when a config file cannot be read, parsed, or validated."""


def load_config(path: Path) -> Config:
    """Load and validate a YAML config file.

    Wraps file I/O and YAML parsing errors in ConfigError with the path for
    context. Pydantic validation errors propagate unchanged (their messages
    are already structured and actionable).
    """
    try:
        raw = path.read_text()
    except OSError as e:
        raise ConfigError(f"could not read config at {path}: {e}") from e
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    return Config.model_validate(data)
