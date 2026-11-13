"""Client IA au format OpenAI (« chat completions »), compatible xAI/Grok et autres fournisseurs."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

log = logging.getLogger("app.ai")


class AIError(Exception):
    """Erreur présentable telle quelle à l'utilisateur (en français)."""


@dataclass
class AIConfig:
    base_url: str
    model: str
    api_key: str
    temperature: float = 0.7


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AIResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Message « assistant » brut, à remettre dans l'historique avant les résultats d'outils.
    assistant_message: dict[str, Any] = field(default_factory=dict)


class AIClient(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict] | None = None) -> AIResponse: ...


class OpenAICompatClient:
    def __init__(self, config: AIConfig, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 60.0):
        self.config = config
        self._transport = transport
        self._timeout = timeout

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict] | None = None) -> AIResponse:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.config.api_key}", "Content-Type": "application/json"}

        last_error: AIError | None = None
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(1.5)
            try:
                async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                    resp = await client.post(url, json=body, headers=headers)
            except httpx.TimeoutException:
                last_error = AIError("Le fournisseur d'IA n'a pas répondu à temps. Réessayez dans un instant.")
                continue
            except httpx.HTTPError:
                last_error = AIError(
                    "Impossible de joindre le fournisseur d'IA. Vérifiez l'URL de base sur la page IA."
                )
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = AIError(
                    "Le fournisseur d'IA limite les requêtes ou vous n'avez plus de crédit (erreur 429)."
                    if resp.status_code == 429
                    else f"Le fournisseur d'IA est momentanément indisponible (erreur {resp.status_code})."
                )
                continue
            if resp.status_code in (401, 403):
                raise AIError("La clé API a été refusée par le fournisseur. Vérifiez-la sur la page IA.")
            if resp.status_code == 404:
                raise AIError("Modèle ou adresse introuvable. Vérifiez l'URL de base et le nom du modèle.")
            if resp.status_code >= 400:
                raise AIError(f"Le fournisseur d'IA a refusé la demande (erreur {resp.status_code}) : {_error_detail(resp)}")
            return _parse(resp)
        assert last_error is not None
        raise last_error


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        return str(err)[:300]
    except Exception:
        return resp.text[:300]


def _parse(resp: httpx.Response) -> AIResponse:
    try:
        message = resp.json()["choices"][0]["message"]
    except Exception as exc:
        raise AIError("Réponse inattendue du fournisseur d'IA (format non reconnu).") from exc
    content = message.get("content") or ""
    if isinstance(content, list):  # certains fournisseurs renvoient des blocs
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(id=raw.get("id") or f"call_{len(calls)}", name=fn.get("name") or "", arguments=args))
    assistant_message = {"role": "assistant", "content": content or None}
    if message.get("tool_calls"):
        assistant_message["tool_calls"] = message["tool_calls"]
    return AIResponse(text=content.strip(), tool_calls=calls, assistant_message=assistant_message)
