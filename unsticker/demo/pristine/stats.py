def summarize(rows):
    scores = [r["scores"] for r in rows]
    top = max(rows, key=lambda r: r["score"])["name"]
    return {"avg": sum(scores) / len(scores), "top": top}
