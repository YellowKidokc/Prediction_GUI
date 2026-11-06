"""The NLP steps the planner can choose from. Each step: (docs, params, results) -> results.

results is {doc_path: {step_name: output}} plus a "_corpus" key for corpus-wide outputs.
A step whose optional library is missing reports itself unavailable; the plan carries on.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from . import llm

WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
STOP = set("""the and for are but not you all any can had her was one our out has have this that with
from they will would there their what about which when your said each she them then into than
also been more some could these other its may such only over most very just where how who why
were does did doing being because while those here both through between after before under""".split())

CATALOG: dict[str, dict] = {}


def step(name: str, needs: str | None = None, desc: str = "", params: dict | None = None):
    def wrap(fn):
        CATALOG[name] = {"fn": fn, "needs": needs, "desc": desc, "params": params or {}}
        return fn
    return wrap


def available(name: str) -> bool:
    needs = CATALOG[name]["needs"]
    if not needs:
        return True
    if needs == "llm":
        return True  # checked at call time; falls back per document
    try:
        __import__(needs)
        return True
    except ImportError:
        return False


def describe() -> list[dict]:
    return [{"step": n, "description": s["desc"], "params": s["params"], "requires": s["needs"] or "stdlib",
             "available": available(n)} for n, s in CATALOG.items()]


def body(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # drop YAML frontmatter


def tokens(text: str) -> list[str]:
    text = body(text)
    return [w.lower() for w in WORD.findall(text) if w.lower() not in STOP]


@step("stats", desc="word/sentence counts, avg sentence length")
def stats(docs, params, out):
    for d in docs:
        sents = [s for s in re.split(r"[.!?]+\s", d.text) if s.strip()]
        w = len(d.text.split())
        out[d.path]["stats"] = {"words": w, "sentences": len(sents),
                                "avg_sentence_words": round(w / max(1, len(sents)), 1)}


@step("markdown_structure", desc="Obsidian/markdown: frontmatter keys, headings, #tags, [[wikilinks]]")
def markdown_structure(docs, params, out):
    for d in docs:
        fm = {}
        m = re.match(r"---\n(.*?)\n---", d.text, flags=re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1); fm[k.strip()] = v.strip()
        out[d.path]["markdown_structure"] = {
            "frontmatter": fm,
            "headings": re.findall(r"^#{1,6}\s+(.+)$", d.text, flags=re.M)[:30],
            "tags": sorted(set(re.findall(r"(?<![\w#])#([A-Za-z][\w/\-]+)", d.text)))[:30],
            "wikilinks": sorted(set(l.split("|")[0] for l in re.findall(r"\[\[([^\]]+)\]\]", d.text)))[:60]}


@step("keywords", desc="TF-IDF top terms per document", params={"top": 10})
def keywords(docs, params, out):
    top = int(params.get("top", 10))
    tfs = [Counter(tokens(d.text)) for d in docs]
    df = Counter(t for tf in tfs for t in tf)
    n = len(docs)
    for d, tf in zip(docs, tfs):
        total = sum(tf.values()) or 1
        score = {t: (c / total) * math.log((1 + n) / (1 + df[t]) + 1) for t, c in tf.items()}
        out[d.path]["keywords"] = [t for t, _ in sorted(score.items(), key=lambda x: -x[1])[:top]]
    out["_corpus"]["top_terms"] = [t for t, _ in df.most_common(40)]


@step("entities", desc="named entities (spaCy if installed, else capitalised-phrase heuristic)", params={"top": 15})
def entities(docs, params, out):
    top = int(params.get("top", 15))
    nlp = None
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
    except Exception:  # noqa: BLE001
        pass
    for d in docs:
        if nlp:
            ents = Counter(f"{e.text} [{e.label_}]" for e in nlp(d.text[:100_000]).ents)
        else:
            ents = Counter(m for m in re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", d.text))
        out[d.path]["entities"] = [e for e, _ in ents.most_common(top)]


@step("near_duplicates", desc="pairs of documents that are near-copies (shingle Jaccard)", params={"threshold": 0.8})
def near_duplicates(docs, params, out):
    th = float(params.get("threshold", 0.8))
    sh = {}
    for d in docs:
        t = tokens(d.text)
        sh[d.path] = {" ".join(t[i:i + 5]) for i in range(max(1, len(t) - 4))}
    paths, pairs = list(sh), []
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            A, B = sh[a], sh[b]
            if A and B:
                j = len(A & B) / len(A | B)
                if j >= th:
                    pairs.append({"a": a, "b": b, "jaccard": round(j, 3)})
    out["_corpus"]["near_duplicates"] = pairs


@step("clusters", needs="sklearn", desc="group documents by topic (TF-IDF + KMeans)", params={"k": 6})
def clusters(docs, params, out):
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    k = min(int(params.get("k", 6)), len(docs))
    if k < 2:
        return
    vec = TfidfVectorizer(max_features=5000, stop_words="english")
    X = vec.fit_transform([d.text for d in docs])
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    terms = vec.get_feature_names_out()
    labels = {i: ", ".join(terms[j] for j in c.argsort()[-5:][::-1]) for i, c in enumerate(km.cluster_centers_)}
    for d, lab in zip(docs, km.labels_):
        out[d.path]["clusters"] = {"id": int(lab), "label": labels[int(lab)]}
    out["_corpus"]["clusters"] = labels


@step("summarize", needs="llm", desc="DeepSeek: 2-3 sentence summary per document", params={"max_docs": 25})
def summarize(docs, params, out):
    for d in docs[: int(params.get("max_docs", 25))]:
        try:
            out[d.path]["summarize"] = llm.chat(
                "Summarise the document in 2-3 plain sentences. No preamble." + params.get("instructions", ""),
                d.text[:12000], timeout=120)
        except llm.LLMUnavailable as e:
            out[d.path]["summarize"] = f"(unavailable: {e})"; break


@step("classify", needs="llm", desc="DeepSeek: put each document in one of the given labels",
      params={"labels": ["paper", "note", "draft", "data", "other"], "max_docs": 50})
def classify(docs, params, out):
    labels = params.get("labels") or ["other"]
    for d in docs[: int(params.get("max_docs", 50))]:
        try:
            r = llm.chat_json(f"Classify the document into exactly one of {labels}. "
                              'Return {"label": ..., "confidence": 0-1, "reason": short}. '
                              + params.get("instructions", ""), d.text[:8000], timeout=120)
            out[d.path]["classify"] = r
        except llm.LLMUnavailable as e:
            out[d.path]["classify"] = {"label": None, "error": str(e)}; break


@step("extract", needs="llm", desc="DeepSeek: pull named fields out of each document as JSON",
      params={"fields": ["title", "main_claim"], "max_docs": 25})
def extract(docs, params, out):
    fields = params.get("fields") or ["title"]
    for d in docs[: int(params.get("max_docs", 25))]:
        try:
            out[d.path]["extract"] = llm.chat_json(
                f"Extract these fields from the document: {fields}. Use null when absent; never invent. "
                + params.get("instructions", ""), d.text[:12000], timeout=120)
        except llm.LLMUnavailable as e:
            out[d.path]["extract"] = {"error": str(e)}; break
