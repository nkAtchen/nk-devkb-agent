from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path | str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class RuntimeConfig:
    llm_provider: str = "mock"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""

    @classmethod
    def from_env_file(cls, path: Path | str) -> "RuntimeConfig":
        values = load_env_file(path)
        return cls(
            llm_provider=values.get("LLM_PROVIDER", "mock"),
            llm_model=values.get("LLM_MODEL", ""),
            llm_api_key=values.get("LLM_API_KEY", ""),
            llm_base_url=values.get("LLM_BASE_URL", ""),
        )

    @classmethod
    def from_root(cls, root: Path | str) -> "RuntimeConfig":
        root_path = Path(root)
        values = load_env_file(root_path / ".env")
        merged = dict(values)
        for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL"):
            if key in os.environ:
                merged[key] = os.environ[key]
        return cls(
            llm_provider=merged.get("LLM_PROVIDER", "mock"),
            llm_model=merged.get("LLM_MODEL", ""),
            llm_api_key=merged.get("LLM_API_KEY", ""),
            llm_base_url=merged.get("LLM_BASE_URL", ""),
        )

    def use_remote_llm(self) -> bool:
        return self.llm_provider != "mock" and bool(self.llm_api_key and self.llm_model and self.llm_base_url)
