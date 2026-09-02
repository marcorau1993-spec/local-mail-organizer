"""Local Ollama availability checks."""

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    def status(self) -> dict[str, object]:
        response = httpx.get(f"{self._base_url}/api/tags", timeout=5.0)
        response.raise_for_status()
        names = {item.get("name") for item in response.json().get("models", [])}
        return {"reachable": True, "model": self._model, "model_available": self._model in names}
