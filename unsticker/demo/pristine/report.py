"""Tiny demo program with two planted breaks."""
from stats import summarize

rows = [{"name": "alpha", "score": 3}, {"name": "beta", "score": 5}, {"name": "gamma", "score": 4}]
result = summarize(rows)
print(f"Average score: {result['avg']:.2f}  ✓")
print(f"Top: {result['top']}")
