import json
import os


def load_lessons():
    path = os.path.join(os.path.dirname(__file__), "..", "bot", "lessons.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


LESSONS = load_lessons()
