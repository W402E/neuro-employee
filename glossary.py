# -*- coding: utf-8 -*-
r"""GLOSSARY — помощник по сокращениям (English identifiers, 23.11.2026).

Переписано с русского на английские имена по требованию куратора: «никогда не используйте
кириллицу для имён переменных и функций; то же относится к именам модулей и хранимым данным».

Данные лежат в `data/abbreviations.json`:
    {
      "updated": "…",
      "how_to_edit": "…",
      "abbreviations": [
         {"code": "СНИЛС", "full": "страховой номер индивидуального лицевого счёта",
          "latin": "SNILS", "spoken": "снилс", "note": "…",
          "source": "27-ФЗ", "variants": [{"meaning": "…", "author": "…", "when": "…"}]}
      ]
    }

Почему варианты: слово пользователя — один человек понимает сокращение так, другой иначе,
и модель должна видеть оба значения, а не одно.
"""
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: BLE001
    pass

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(MODULE_DIR, "data", "abbreviations.json")


def load_glossary(path=DEFAULT_PATH):
    """Return abbreviation entries: {KEY: entry}.

    В файле записи хранятся списком: `{"code": "ЖКХ", "full": …}`. Так имена полей
    остаются английскими, а само сокращение лежит значением поля `code`.
    Прежний вид (словарь, где ключ — само сокращение) читается тоже.
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    raw = data.get("abbreviations", {})
    if isinstance(raw, dict):
        return raw
    entries = {}
    for record in raw:
        code = (record.get("code") or "").strip()
        if not code:
            continue
        entries[code] = {key: value for key, value in record.items() if key != "code"}
    return entries


def save_glossary(entries, path=DEFAULT_PATH):
    """Write entries back as a list of records, keeping the header fields."""
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    data["abbreviations"] = [dict({"code": code}, **entry) for code, entry in entries.items()]
    data["updated"] = time.strftime("%d.%m.%Y")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)


def find_in_text(text, path=DEFAULT_PATH):
    """Which abbreviations occur in the text (longest first, word boundaries)."""
    entries = load_glossary(path)
    found = []
    rest = text or ""
    for key in sorted(entries, key=len, reverse=True):
        pattern = r"(?<![А-Яа-яЁёA-Za-z])" + re.escape(key) + r"(?![А-Яа-яЁёA-Za-z])"
        flags = re.IGNORECASE if len(key) > 3 else 0
        if re.search(pattern, rest, flags):
            found.append(key)
            rest = re.sub(pattern, " ", rest, flags=flags)
    return found


def explain(keys, path=DEFAULT_PATH):
    """Keys → details for tooltips and for the model prompt."""
    entries = load_glossary(path)
    result = {}
    for key in keys:
        entry = entries.get(key)
        if not entry:
            continue
        result[key] = {
            "full": entry.get("full", ""),
            "latin": entry.get("latin", ""),
            "spoken": entry.get("spoken", ""),
            "note": entry.get("note", ""),
            "source": entry.get("source", ""),
            "variants": [item.get("meaning", "") for item in entry.get("variants", [])],
        }
    return result


def tooltip(key, path=DEFAULT_PATH):
    """One-line hint for the mouse cursor."""
    entry = load_glossary(path).get(key) or {}
    if not entry:
        return ""
    parts = [entry.get("full", "")]
    if entry.get("latin"):
        parts.append("latin: " + entry["latin"])
    if entry.get("spoken"):
        parts.append("spoken: " + entry["spoken"])
    if entry.get("note"):
        parts.append(entry["note"])
    for variant in entry.get("variants", []):
        parts.append("own meaning (%s): %s" % (variant.get("author", "someone"),
                                               variant.get("meaning", "")))
    if entry.get("source"):
        parts.append("source: " + entry["source"])
    return " · ".join(part for part in parts if part)


def add_variant(key, meaning, author="user", path=DEFAULT_PATH):
    """Add a personal meaning; previous meanings are never overwritten."""
    entries = load_glossary(path)
    key = (key or "").strip()
    meaning = (meaning or "").strip()
    if not key or not meaning:
        return "need both abbreviation and meaning"
    if key not in entries:
        entries[key] = {"full": meaning, "latin": "", "spoken": "", "note": "added by hand",
                        "source": "word of " + author, "variants": []}
    entries[key].setdefault("variants", [])
    for variant in entries[key]["variants"]:
        if variant.get("meaning", "").strip().lower() == meaning.lower():
            return "this meaning is already there"
    entries[key]["variants"].append({"meaning": meaning, "author": author,
                                     "when": time.strftime("%d.%m.%Y %H:%M")})
    save_glossary(entries, path)
    return "added: %s → %s (total meanings: %d)" % (
        key, meaning, 1 + len(entries[key]["variants"]))


def shooting_advice(characters, digits, document_type="", is_photo=False):
    """What to ask the user if the scan was read badly."""
    if not is_photo and characters >= 200:
        return ""
    if characters >= 400 and digits >= 10:
        return ""
    advice = []
    if characters < 60:
        advice.append("take the photo again, closer: the sheet should fill the frame "
                      "(about 10-15 cm from the phone)")
    if digits < 5:
        advice.append("a close-up of the area with numbers (sum, date, number) — "
                      "a second shot will be merged with the first")
    advice.append("straight and in good light, no tilt: put the sheet on the table, camera above")
    advice.append("if the sheet is crumpled — flatten it or shoot in parts: "
                  "header, table, signature")
    advice.append("format JPG or PNG (HEIC from iPhones cannot be read)")
    if (document_type or "").startswith("receipt"):
        advice.append("for a receipt: shoot the TOTAL line and the line with the QR code separately")
    return "For a better reading: " + "; ".join(advice) + "."


def list_all(path=DEFAULT_PATH):
    """All abbreviations sorted, for the page."""
    return sorted(load_glossary(path).items(), key=lambda pair: pair[0].upper())


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--key" in arguments and "--meaning" in arguments:
        print(add_variant(arguments[arguments.index("--key") + 1],
                          arguments[arguments.index("--meaning") + 1]))
    else:
        for key, entry in list_all():
            print("%-10s %s" % (key, entry.get("full", "")[:70]))
