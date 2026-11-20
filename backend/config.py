from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    participants: list[Literal["human", "ai"]] = Field(min_length=3, max_length=3)
    rounds: int = Field(ge=2, le=2)
    discussion_duration_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def require_human(self) -> "ExperimentConfig":
        if "human" not in self.participants:
            raise ValueError("at least one participant must be human")
        return self


def load_config(path: Path) -> ExperimentConfig:
    try:
        with path.open(encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Unable to load configuration from {path}: {exc}") from exc
    return ExperimentConfig.model_validate(data)
