import json
import re
import subprocess
from urllib.parse import quote_plus, urlparse


class WebAccess:
    """Small local web client used only after ServerHelpr's approval gate."""

    def __init__(self, config: dict):
        self.config = config.get("web", {})
        self.timeout = int(self.config.get("timeout", 15))
        self.max_bytes = int(self.config.get("max_bytes", 200000))

    def _check_url(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only http:// and https:// URLs are allowed.")
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("Local/private web targets are blocked.")
        if re.match(r"^(127\\.|10\\.|192\\.168\\.|169\\.254\\.|0\\.)", host):
            raise ValueError("Private/local IP web targets are blocked.")
        return url

    def search(self, query: str, limit: int = 5):
        if not query.strip():
            raise ValueError("Search query cannot be empty.")
        limit = max(1, min(int(limit), 10))
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        body = self.fetch(url)["content"]

        results = []
        for match in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.I | re.S,
        ):
            href = re.sub(r"<.*?>", "", match.group(1))
            title = re.sub(r"<.*?>", "", match.group(2))
            title = re.sub(r"\\s+", " ", title).strip()
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("http"):
                results.append({"title": title, "url": href})
            if len(results) >= limit:
                break

        return {"ok": True, "query": query, "results": results}

    def fetch(self, url: str):
        url = self._check_url(url)
        completed = subprocess.run(
            [
                "curl", "--fail", "--silent", "--show-error", "--location",
                "--max-time", str(self.timeout),
                "--max-filesize", str(self.max_bytes),
                "--user-agent", "ServerHelpr/1.0",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout + 2,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "curl failed")
        content = completed.stdout[:self.max_bytes]
        return {"ok": True, "url": url, "content": content}


def web_tool_command(name: str, args: dict) -> str:
    if name == "web_search":
        return f"WEB SEARCH: {str(args.get('query', '')).strip()}"
    if name == "web_fetch":
        return f"WEB FETCH: {str(args.get('url', '')).strip()}"
    return ""
