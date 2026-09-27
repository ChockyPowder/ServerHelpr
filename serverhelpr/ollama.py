import requests


class OllamaClient:
    def __init__(self, config: dict):
        cfg = config.get("ollama", {})
        self.url = cfg.get("url", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("model", "qwen3.5:4b")
        self.temperature = float(cfg.get("temperature", 0.1))
        self.num_ctx = int(cfg.get("num_ctx", 4096))
        self.num_predict = int(cfg.get("num_predict", 128))
        self.keep_alive = cfg.get("keep_alive", "30m")
        self.think = cfg.get("think", False)

    def chat(self, messages: list, tools: list) -> dict:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=300,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            raise RuntimeError(
                f"Ollama API error {response.status_code}: {detail or response.reason}"
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not reach Ollama at {self.url}: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Ollama returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise RuntimeError("Ollama returned an unexpected response shape")

        return data
