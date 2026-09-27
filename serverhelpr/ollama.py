import requests


class OllamaClient:
    def __init__(self, config: dict):
        cfg = config.get("ollama", {})
        self.url = cfg.get("url", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("model", "qwen3.5:4b")
        self.temperature = float(cfg.get("temperature", 0.1))

    def chat(self, messages: list, tools: list) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"temperature": self.temperature},
        }

        response = requests.post(
            f"{self.url}/api/chat",
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        return response.json()
