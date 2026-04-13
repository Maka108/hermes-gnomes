from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hermes_gnomes.config import Config, ConfigError, load_config


def _sample_config() -> dict:
    return {
        "business_name": "gnome-statues",
        "timezone": "America/Los_Angeles",
        "quiet_hours": {"start": "22:00", "end": "07:00"},
        "default_post_time": "09:00",
        "weekly_report_time": "08:00",
        "weekly_report_day": "Sunday",
        "approval_mode": "balanced",
        "rate_limits": {
            "default": {"per_minute": 5, "per_day": 50},
            "etsy_api_client": {"per_minute": 5, "per_day": 50},
        },
        "approval_repings_hours": [3, 6],
        "anomaly_baseline_days": 7,
        "anomaly_multiplier": 3.0,
        "llm": {
            "primary": "anthropic/claude-haiku-4.5",
            "fallbacks": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"],
        },
        "paths": {
            "data_dir": "data",
            "memory_dir": "memory",
            "skills_dir": "skills",
            "sessions_dir": "sessions",
        },
    }


def test_load_config_parses_sample(tmp_config_dir: Path) -> None:
    config_path = tmp_config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(_sample_config()))

    cfg = load_config(config_path)

    assert isinstance(cfg, Config)
    assert cfg.business_name == "gnome-statues"
    assert cfg.timezone == "America/Los_Angeles"
    assert cfg.quiet_hours.start == "22:00"
    assert cfg.quiet_hours.end == "07:00"
    assert cfg.approval_mode == "balanced"
    assert cfg.approval_repings_hours == [3, 6]
    assert cfg.llm.primary == "anthropic/claude-haiku-4.5"
    assert cfg.llm.fallbacks == ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5"]


def test_rate_limit_for_tool_returns_default_when_unknown(tmp_config_dir: Path) -> None:
    config_path = tmp_config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(_sample_config()))

    cfg = load_config(config_path)

    default = cfg.rate_limit_for("some_unknown_tool")
    assert default.per_minute == 5
    assert default.per_day == 50


def test_rate_limit_for_tool_returns_specific(tmp_config_dir: Path) -> None:
    config_path = tmp_config_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(_sample_config()))

    cfg = load_config(config_path)

    etsy = cfg.rate_limit_for("etsy_api_client")
    assert etsy.per_minute == 5
    assert etsy.per_day == 50


def test_invalid_approval_mode_raises(tmp_config_dir: Path) -> None:
    bad = _sample_config()
    bad["approval_mode"] = "nonsense"
    path = tmp_config_dir / "config.yaml"
    path.write_text(yaml.safe_dump(bad))

    with pytest.raises(ValidationError, match="approval_mode"):
        load_config(path)


def test_rate_limit_for_raises_when_default_missing(tmp_config_dir: Path) -> None:
    data = _sample_config()
    del data["rate_limits"]["default"]
    path = tmp_config_dir / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    cfg = load_config(path)

    with pytest.raises(KeyError, match="default"):
        cfg.rate_limit_for("some_unknown_tool")


def test_load_config_raises_config_error_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError, match="could not read"):
        load_config(missing)


def test_load_config_raises_config_error_on_malformed_yaml(tmp_config_dir: Path) -> None:
    path = tmp_config_dir / "bad.yaml"
    path.write_text("not: valid: yaml: [unbalanced")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)
