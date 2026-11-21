"""Ask the AI for a better category for already-saved transactions. Suggestions only: nothing is saved here."""
import json
import re
import time
from typing import Iterator

import ai_worker
from parsers.category_suggester import VALID_CATEGORIES

BATCH = 20
BUDGET_SECONDS = 240   # under the browser's 300s timeout
MAX_TOKENS = 4000      # free reasoning models spend much of the budget thinking
CATEGORIES = sorted(VALID_CATEGORIES - {"Other", "Internal Transfer"})


def _ask(rows: list[dict]) -> dict[int, str]:
    prompt = (
        "You categorize a Nigerian school's transactions.\n"
        "For each item pick the best category, using EXACTLY one of these names: " + ", ".join(CATEGORIES) + ".\n"
        "Only use what is visible in the description and vendor. If unsure, return the current category.\n"
        "Money received from a person or parent is usually School Fees; do not use transfer categories.\n\n"
        "Items:\n" + json.dumps(rows, ensure_ascii=False) + "\n\n"
        'Return ONLY a JSON array: [{"id": <id>, "category": "<category>"}]'
    )
    match = re.search(r"\[[\s\S]*\]", ai_worker._clean_json(ai_worker.call_ai_text(prompt, MAX_TOKENS)))
    try:
        answers = json.loads(match.group()) if match else []
    except ValueError:
        return {}
    asked = {r["id"] for r in rows}
    return {a["id"]: a["category"].strip() for a in answers
            if isinstance(a, dict) and a.get("id") in asked and isinstance(a.get("category"), str) and a["category"].strip() in CATEGORIES}


def suggest_categories(rows: list[dict]) -> Iterator[dict[int, str]]:
    """rows: [{"id", "type", "description", "vendor", "category"}]. Yields {id: category} per batch."""
    deadline = time.monotonic() + BUDGET_SECONDS
    for start in range(0, len(rows), BATCH):
        if time.monotonic() > deadline:
            return
        yield _ask(rows[start:start + BATCH])
