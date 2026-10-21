import json
import random
from pathlib import Path

DATA = Path(__file__).parent / "data" / "tasks.json"


def tasks(seed):
    items = json.loads(DATA.read_text())
    random.Random(seed).shuffle(items)
    return items


def grade(answer, expected):
    # Predeclared exact match after whitespace trimming and case folding. No LLM judge.
    return answer.strip().casefold() == expected.strip().casefold()


def repeated_prompts(n, repeat_rate, seed):
    unique = max(1, round(n * (1 - repeat_rate)))
    base = [f"Public synthetic item {i}" for i in range(unique)]
    rng = random.Random(seed)
    items = base + [rng.choice(base) for _ in range(n - unique)]
    rng.shuffle(items)
    return items
