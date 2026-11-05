"""A small Retell REST client: just what setting up and testing the receptionist needs.

Base https://api.retellai.com, `Authorization: Bearer <API key>`. Errors come back as
{"status": "error", "message": "..."}; that message is shown, the key never is.
A 429 ("Account rate limited") is retried with a short backoff, then reported.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import httpx

BASE = "https://api.retellai.com"


class RetellError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, message: str):
        self.status = status
        super().__init__(f"Retell {method} {path} -> HTTP {status}: {message}")


class RetellAPI:
    def __init__(self, api_key: str, client: Optional[httpx.Client] = None, retries_429: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise ValueError("a Retell API key is needed")
        self._client = client or httpx.Client(base_url=BASE, timeout=30)
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.retries_429 = retries_429
        self.sleep = sleep

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        delay = 1.0
        for attempt in range(self.retries_429 + 1):
            r = self._client.request(method, path, json=body, headers=self._headers)
            if r.status_code == 429 and attempt < self.retries_429:
                wait = r.headers.get("Retry-After")
                self.sleep(float(wait) if wait and wait.replace(".", "", 1).isdigit() else delay)
                delay *= 2
                continue
            break
        if r.status_code >= 400:
            try:
                message = r.json().get("message") or r.text[:300]
            except ValueError:
                message = r.text[:300]
            raise RetellError(r.status_code, method, path, message)
        return r.json() if r.content else None

    # response engine -----------------------------------------------------------------------------
    def create_llm(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("POST", "/create-retell-llm", body)

    def update_llm(self, llm_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("PATCH", f"/update-retell-llm/{llm_id}", body)

    def delete_llm(self, llm_id: str) -> None:
        self._call("DELETE", f"/delete-retell-llm/{llm_id}")

    # agent ---------------------------------------------------------------------------------------
    def create_agent(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("POST", "/create-agent", body)

    def update_agent(self, agent_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("PATCH", f"/update-agent/{agent_id}", body)

    def delete_agent(self, agent_id: str) -> None:
        self._call("DELETE", f"/delete-agent/{agent_id}")

    # calls ---------------------------------------------------------------------------------------
    def create_web_call(self, agent_id: str) -> Dict[str, Any]:
        return self._call("POST", "/v3/create-web-call", {"agent_id": agent_id})

    def get_call(self, call_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/v2/get-call/{call_id}")
