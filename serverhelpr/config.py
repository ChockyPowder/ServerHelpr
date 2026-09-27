from pathlib import Path
import os
import yaml

DEFAULT_CONFIG = "config.yaml"


def expand(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))


def load_config(path: str = DEFAULT_CONFIG) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"{config_path} not found. Copy config.example.yaml to config.yaml first."
        )

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config.setdefault("servers", {})
    config.setdefault("policy", {})
    config.setdefault("ollama", {})
    config.setdefault("ssh", {})

    return config
