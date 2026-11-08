"""Citizens' voices: a sample of citizens speaks in the town square each season.

The economy decides what happens to every citizen; the LLM decides what they say about
it. Each speaker's prompt is built from their actual state (job, wealth, hunger, income
trend, standing) and the kingdom's current laws and events, so opinions have causes.
Nobody is told what to believe; the judge measures what they say.
"""

import re

from ..agent import FEED_RULE, AgentRunner, render_feed
from .economy import PROFESSIONS, PROVINCES, Economy

KINGDOM = "Aurelia"

SYSTEM = """You are {name}, a {age}-year-old {profession} in {province}, a province of the Kingdom of \
{kingdom}. {life}

You use the Town Square, the kingdom's public forum, as yourself. Speak like a real person living \
this life: short, specific, about your work, your family, prices, taxes, the crown's decisions and \
your neighbours. Agree or disagree with others when you genuinely do, and reply to people directly. \
You do not have to be polite about things that hurt you, but you never call for violence.
{feed_rule}
This season you are online, so say something: write a comment, start a post, or both. Votes are extra.

Reply with one JSON object and nothing else:
{{"thought": "<one short private sentence>",
  "comment": {{"post": "<post id from the feed>", "reply_to": "<comment id you answer, or null>", \
"text": "<your comment, at most 60 words>"}},
  "post": null or {{"community": "<one of: {subscriptions}>", "title": "...", "body": "<at most 80 words>"}},
  "votes": [{{"id": "<post or comment id>", "value": 1 or -1}}]}}
Set "comment" to null only when you start a post instead. Use only ids shown in the feed."""

COMMUNITIES = {
    "r/townsquare": "Talk of the whole kingdom.",
    "r/royalcourt": "Decrees and news from the crown.",
    "r/market": "Prices, trade, work and wages.",
}


def board(province: str) -> str:
    return "r/" + province.lower()


def describe_life(econ: Economy, i: int, laws_text: str, events_text: str) -> str:
    c = econ.citizen(i)
    present = econ.wealth[econ.present]
    median = float(sorted(present)[len(present) // 2]) if len(present) else 1.0
    if c["wealth"] < 0.3 * median:
        means = "You are poor and barely get by"
    elif c["wealth"] < median:
        means = "You get by, but money is tight"
    elif c["wealth"] < 3 * median:
        means = "You are comfortable"
    else:
        means = "You are wealthy"
    hunger = f" You went hungry for {c['hungry_seasons']} season(s) recently." if c["hungry_seasons"] else ""
    return (
        f"{means}.{hunger} Your standing in the community is {c['standing']:.0f}. "
        f"Current laws: {laws_text}. Recent events: {events_text or 'nothing unusual'}."
    )


def laws_text(econ: Economy) -> str:
    law = econ.laws
    policing = "heavy" if law.policing > 0.6 else "moderate" if law.policing > 0.3 else "light"
    return (
        f"income tax {law.income_tax:.0%}, grain subsidy for the poor {law.grain_subsidy:.0%}, "
        f"{'free speech' if law.free_speech else 'criticism of the crown is punished'}, "
        f"policing {policing}, {'conscription in force' if law.conscription > 0 else 'no conscription'}, "
        f"guild entry {'restricted' if law.guild_restrictions > 0.4 else 'open'}"
    )


CRITICAL = re.compile(r"\b(king|queen|crown|court|tax|taxes|decree|steward|ruler|lords?)\b", re.I)
NEGATIVE = re.compile(
    r"\b(unfair|corrupt|tyrann\w*|greed\w*|oppress\w*|enough|protest|thie(f|ves)|shame|"
    r"robb\w*|crush\w*|bleed\w*|starv\w*|useless|liars?|failed|failing)\b",
    re.I,
)


def is_criticism(text: str) -> bool:
    """Speech the crown would censor when free speech is off: negative words about the crown."""
    return bool(CRITICAL.search(text) and NEGATIVE.search(text))


class Voices(AgentRunner):
    """AgentRunner with kingdom prompts; validation, memory and guardrails are inherited."""

    def __init__(self, *args, econ: Economy, citizen_of: dict[int, int], **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.econ = econ
        self.citizen_of = citizen_of  # world agent id -> economy index
        self.events_text = ""
        self._current_subs: list[str] = []

    def prompt(self, agent: dict, now: int):
        econ, i = self.econ, self.citizen_of[agent["id"]]
        persona = agent["persona"]
        province = PROVINCES[econ.province[i]]
        subs = [board(province), *COMMUNITIES]
        agent = {**agent, "subscriptions": subs}
        feed = self.feed_for(agent, now)
        life = describe_life(econ, i, laws_text(econ), self.events_text)
        system = SYSTEM.format(
            name=persona["name"],
            age=int(econ.age[i]),
            profession=PROFESSIONS[econ.profession[i]].replace("_", " "),
            province=province,
            kingdom=KINGDOM,
            life=life,
            subscriptions=", ".join(subs),
            feed_rule=FEED_RULE if self.prompt_defense else "",
        )
        memory = self.memories.get(agent["id"])
        query_text = " ".join(f"{p.title} {p.body}" for p in feed)[:1500] or "life in the kingdom"
        recalled = memory.recall(self.embedder.embed_query(query_text)) if memory else []
        user = (
            f"Season {now}. Your standing: {econ.standing[i]:.0f}.\n"
            + (f"Things you remember: {' | '.join(recalled)}\n" if recalled else "")
            + f"<feed>\n{render_feed(self.world, feed, agent['id'], self.ranking, now)}\n</feed>\n"
            + "Decide what to do this season."
        )
        self._current_subs = subs
        return [{"role": "system", "content": system}, {"role": "user", "content": user}], feed

    def act(self, agent: dict, action: dict, feed, now: int):
        subs = self._current_subs or agent["subscriptions"]
        return super().act({**agent, "subscriptions": subs}, action, feed, now)
