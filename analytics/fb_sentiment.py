#!/usr/bin/env python3
"""Georgian sentiment analysis — simple rules-based approach.

Uses configurable word lists from config/sentiment_words.json.
Classifies text as positive/negative/neutral based on keyword matches.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config" / "sentiment_words.json"
_sentiment_words: dict[str, list[str]] = {}


def _load_words():
    """Load sentiment word lists from config file (cached)."""
    global _sentiment_words
    if _sentiment_words:
        return _sentiment_words
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _sentiment_words = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[Sentiment] Failed to load words: {e}")
        _sentiment_words = {"positive": [], "negative": []}
    return _sentiment_words


def analyze_comment(text: str) -> str:
    """Analyze a single comment.

    Returns: 'positive', 'negative', or 'neutral'
    """
    if not text:
        return "neutral"

    words = _load_words()
    text_lower = text.lower()

    pos_count = sum(1 for w in words.get("positive", []) if w.lower() in text_lower)
    neg_count = sum(1 for w in words.get("negative", []) if w.lower() in text_lower)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    elif pos_count > 0 and neg_count > 0:
        return "neutral"  # mixed
    return "neutral"


def batch_analyze(texts: list[str]) -> dict:
    """Analyze a batch of comment texts.

    Returns: {
        total: int,
        positive: int,
        negative: int,
        neutral: int,
        positive_pct: float,
        negative_pct: float,
        neutral_pct: float,
        available: bool
    }
    """
    if not texts:
        return {
            "total": 0,
            "positive": 0, "negative": 0, "neutral": 0,
            "positive_pct": 0.0, "negative_pct": 0.0, "neutral_pct": 0.0,
            "available": False,
        }

    results = {"positive": 0, "negative": 0, "neutral": 0}
    for text in texts:
        sentiment = analyze_comment(text)
        results[sentiment] += 1

    total = len(texts)
    return {
        "total": total,
        "positive": results["positive"],
        "negative": results["negative"],
        "neutral": results["neutral"],
        "positive_pct": round(results["positive"] / total * 100, 1),
        "negative_pct": round(results["negative"] / total * 100, 1),
        "neutral_pct": round(results["neutral"] / total * 100, 1),
        "available": True,
    }
