import requests


class OpenRouterClient:
    _API = "https://openrouter.ai/api/v1/chat/completions"
    _MODELS = "https://openrouter.ai/api/v1/models"

    def __init__(self, api_key: str, model: str, site_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.site_url = site_url or "https://wordpress.com"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": "WP AI Poster",
        }

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            self._API,
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def list_models(self) -> list[str]:
        resp = requests.get(
            self._MODELS,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return sorted(m["id"] for m in resp.json().get("data", []))
