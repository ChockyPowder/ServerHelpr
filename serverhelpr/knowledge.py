import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _tokens(text):
    return {t for t in re.findall(r"[a-z0-9_./:-]+", str(text or "").lower()) if len(t) > 2}


class KnowledgeBase:
    def __init__(self, config):
        data_dir = Path(config.get("data_dir", "./data")).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "knowledge.json"
        self.entries = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self):
        self.path.write_text(json.dumps(self.entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def search(self, query, server=None, limit=8):
        wanted = _tokens(query)
        scored = []
        for entry in self.entries:
            if server and entry.get("server") not in (None, server):
                continue
            text = " ".join(str(entry.get(k, "")) for k in ("type", "server", "subject", "content", "tags"))
            score = len(wanted & _tokens(text))
            if score:
                scored.append((score, entry))
        scored.sort(key=lambda x: (-x[0], x[1].get("created_at", "")))
        return [entry for _, entry in scored[:limit]]

    def context(self, query, server=None, limit=8):
        matches = self.search(query, server, limit)
        if not matches:
            return "No relevant stored knowledge."
        return "\n".join(
            f"- {e.get('type')} [{e.get('server') or 'global'}] "
            f"{e.get('subject') or ''}: {e.get('content')} "
            f"(confidence={e.get('confidence', 0.8):.2f})"
            for e in matches
        )

    def add(self, entry_type, content, server=None, subject=None, source="ai", confidence=0.8, tags=None):
        entry = {
            "id": f"k-{int(datetime.now(timezone.utc).timestamp() * 1000000)}",
            "type": entry_type,
            "server": server,
            "subject": subject,
            "content": content.strip(),
            "source": source,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "tags": tags or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.entries.append(entry)
        self._save()
        return entry
