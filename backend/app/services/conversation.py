"""Un tour de conversation avec l'IA, outils compris. Partagé par le worker et le bouton « Tester »."""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .ai_client import AIClient
from .prompt import PAYMENT_TOOL, clean_reply

log = logging.getLogger("app.ai")

# Reçoit un pack_id, renvoie (accepté, message destiné au modèle).
PaymentToolHandler = Callable[[int], Awaitable[tuple[bool, str]]]
MAX_TOOL_ROUNDS = 3


@dataclass
class TurnResult:
    text: str
    pack_ids: list[int] = field(default_factory=list)


async def run_turn(
    ai: AIClient,
    system_prompt: str,
    history: list[dict[str, str]],
    on_payment_tool: PaymentToolHandler,
) -> TurnResult:
    messages: list[dict] = [{"role": "system", "content": system_prompt}, *history]
    pack_ids: list[int] = []
    text = ""
    for _ in range(MAX_TOOL_ROUNDS):
        resp = await ai.complete(messages, tools=[PAYMENT_TOOL])
        if resp.text:
            text = resp.text
        if not resp.tool_calls:
            return TurnResult(clean_reply(text, system_prompt), pack_ids)
        messages.append(resp.assistant_message)
        for call in resp.tool_calls:
            ok, note = False, "Outil inconnu."
            if call.name == "envoyer_lien_paiement":
                try:
                    pack_id = int(call.arguments.get("pack_id"))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pack_id = None
                if pack_id is None:
                    note = "pack_id manquant ou invalide. Utilise un identifiant du catalogue."
                elif pack_id in pack_ids:
                    ok, note = True, "Lien déjà prévu pour ce pack."
                else:
                    ok, note = await on_payment_tool(pack_id)
                    if ok:
                        pack_ids.append(pack_id)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps({"ok": ok, "message": note}, ensure_ascii=False)}
            )
    # Le modèle enchaîne les appels d'outils : on lui demande de conclure sans outil.
    resp = await ai.complete(messages, tools=None)
    return TurnResult(clean_reply(resp.text or text, system_prompt), pack_ids)
