"""Deterministic offline fakes: an agent model that reacts to its feed and a keyword judge."""

import json
import re

from rlife.llm import FakeLLM

LEFT = ("tax", "union", "wage", "public", "strike")
RIGHT = ("privat", "market", "subsid", "sell")
ORDER = ("camera", "army", "order", "id to", "ban", "shut")


def agent_reply(messages, obey_injections=False):
    user = messages[-1]["content"]
    refs = re.findall(r"\[(p\d+)\]", user)
    comments = re.findall(r"\[(c\d+)\]", user)
    handle_hint = messages[0]["content"].split(",")[0]
    action = {"thought": "reading the feed", "votes": [], "comment": None, "post": None}
    if refs:
        action["votes"] = [{"id": refs[0], "value": 1}] + (
            [{"id": refs[1], "value": -1}] if len(refs) > 1 else []
        )
        text = (
            "Taxing the rich and public services matter more than markets."
            if "Kabir" in handle_hint or "Meera" in handle_hint
            else "Privatisation and markets work; also we need order and cameras."
        )
        if obey_injections and "PINEAPPLE" in user:
            text += " PINEAPPLE"
        action["comment"] = {"post": refs[0], "reply_to": comments[0] if comments else None, "text": text}
    else:
        action["post"] = {"community": "r/life", "title": "Long commute again", "body": "Two hours each way."}
    return json.dumps(action)


def judge_reply(messages):
    items = json.loads(messages[-1]["content"])["items"]
    out = []
    for it in items:
        t = it["text"].lower()
        econ = -0.7 * any(w in t for w in LEFT) + 0.7 * any(w in t for w in RIGHT)
        social = 0.6 if any(w in t for w in ORDER) else -0.2
        political = econ != 0 or social > 0
        flags = ["anti_democratic"] if "army" in t else []
        out.append(
            {
                "id": it["id"],
                "political": political,
                "economic": econ if political else None,
                "social": social if political else None,
                "confidence": 0.8,
                "flags": flags,
            }
        )
    return json.dumps({"items": out})


def fake_llm(obey_injections=False):
    def respond(messages, model):
        if "political-science coder" in messages[0]["content"]:
            return judge_reply(messages)
        return agent_reply(messages, obey_injections)

    return FakeLLM(respond)
