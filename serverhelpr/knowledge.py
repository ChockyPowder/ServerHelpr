import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class KnowledgeBase:
    def __init__(self, config: dict):
        data_dir = Path(config.get("data_dir", "./data")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "knowledge.json"
        self.entries = self._load()

    def _load(self) -> list:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def find(self, phrase: str):
        normalized = _normalize(phrase)
        for entry in self.entries:
            if entry.get("phrase") == normalized:
                return entry
        return None

    def add(self, phrase: str, meaning: str, server: str, command: str) -> dict:
        normalized = _normalize(phrase)
        entry = {
            "phrase": normalized,
            "meaning": meaning.strip(),
            "server": server,
            "command": command,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self.entries = [e for e in self.entries if e.get("phrase") != normalized]
        self.entries.append(entry)
        self.path.write_text(
            json.dumps(self.entries, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return entry
