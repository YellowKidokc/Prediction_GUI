"""Name words — predicts a classification from the paper's own name.

Bernoulli Naive Bayes over the words in the paper's name (context["words"]) plus
its folder_class. Built for the sidecar review: order means nothing there, the
paper does. Leave-one-out: when asked about a paper it was trained on, that
paper's own vote is subtracted first, so it can never just echo the answer.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from harness.contract import Engine, Event, Prediction, Candidate, context_key_of

STOP = {"the", "of", "and", "a", "an", "to", "in", "on", "for", "as", "vs", "md"}
VERSION_RE = re.compile(r"^v?\d+(\.\d+)*$")


def tokenize(text: str) -> set[str]:
    words = re.split(r"[^a-z0-9.]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in STOP and not VERSION_RE.match(w)}


class NameWords(Engine):
    """P(label | words in the paper's name, folder_class). Leave-one-out."""

    name = "name_words"
    target = "next_subject"

    def __init__(self) -> None:
        self.by_paper: dict[str, tuple[str, set[str]]] = {}
        self.label_n: Counter = Counter()
        self.tok_n: dict[str, Counter] = defaultdict(Counter)

    @staticmethod
    def _tokens(ctx: dict[str, Any]) -> set[str]:
        toks = tokenize(str(ctx.get("words", "")))
        if ctx.get("folder_class"):
            toks.add(f"fc={ctx['folder_class']}")
        return toks

    def fit(self, events: list[Event]) -> None:
        self.by_paper = {}
        for e in events:
            if "words" not in e.context:
                continue
            paper = str(e.context.get("paper") or e.id)
            self.by_paper[paper] = (e.subject, self._tokens(e.context))
        self.label_n, self.tok_n = Counter(), defaultdict(Counter)
        for label, toks in self.by_paper.values():
            self.label_n[label] += 1
            for t in toks:
                self.tok_n[label][t] += 1

    def predict(self, context: dict[str, Any]) -> Prediction:
        key = context_key_of(context, ("paper",))
        toks = self._tokens(context)
        if not self.label_n or not toks:
            return self.empty(key, "no labelled papers yet" if not self.label_n else "no words to go on")
        label_n = Counter(self.label_n)
        tok_n = {l: Counter(c) for l, c in self.tok_n.items()}
        own = self.by_paper.get(str(context.get("paper", "")))
        if own:  # leave-one-out
            label_n[own[0]] -= 1
            for t in own[1]:
                tok_n[own[0]][t] -= 1
        total = sum(n for n in label_n.values() if n > 0)
        if total == 0:
            return self.empty(key, "only this paper is labelled")
        scores, why = {}, {}
        for label, n in label_n.items():
            if n <= 0:
                continue
            lp = math.log(n / total)
            hits = []
            for t in toks:
                df = tok_n[label][t]
                lp += math.log((df + 1) / (n + 2))
                if df and not t.startswith("fc="):   # folder_class counts, but isn't a "reason"
                    hits.append(f"{t} {df}/{n}")
            scores[label], why[label] = lp, hits
        m = max(scores.values())
        z = sum(math.exp(s - m) for s in scores.values())
        ranked = sorted(scores, key=scores.get, reverse=True)[:5]
        cands = [Candidate(l, round(math.exp(scores[l] - m) / z, 3),
                           ("words: " + ", ".join(sorted(why[l])[:4])) if why[l] else f"prior only ({label_n[l]}/{total})")
                 for l in ranked]
        matched = any(why[l] for l in ranked)
        return Prediction(engine=self.name, target=self.target, context_key=key, candidates=cands,
                          markers={"leave_one_out": bool(own), "trained_on": total, "word_overlap": matched},
                          guidance=f"{cands[0].value} — {cands[0].reason}" if matched
                          else f"{cands[0].value} — no shared words, base rate only")
