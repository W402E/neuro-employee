# -*- coding: utf-8 -*-
r"""CODES — QR, штрих-коды и сверка кодов по классификаторам (English identifiers, 23.11.2026).

Содержит три части:
  1. find_codes()      — QR и одномерные штрих-коды (zxing-cpp, запасной путь — OpenCV).
  2. check_classifier() — контрольные разряды ИНН, СНИЛС, ОГРН и форматы КПП, БИК, ОКУД, ОКПО.
  3. okud_meaning()     — что за форма документа по официальному классификатору ОК 011-93.

Русский текст — только в сообщениях человеку; имена английские (требование куратора).
"""
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: BLE001
    pass

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
OKUD_PATH = os.path.join(MODULE_DIR, "data", "okud_codes.json")

# Сколько цифр в коде и что это за код.
FORMATS = {
    "ИНН": (10, 12, "ИНН: 10 цифр у организации, 12 у человека"),
    "СНИЛС": (11, 11, "СНИЛС: 11 цифр (обычно 123-456-789 01)"),
    "ОГРН": (13, 13, "ОГРН: 13 цифр"),
    "ОГРНИП": (15, 15, "ОГРНИП: 15 цифр"),
    "КПП": (9, 9, "КПП: 9 знаков — 4 цифры, 2 знака, 3 цифры"),
    "БИК": (9, 9, "БИК: 9 цифр, начинается с 04"),
    "ОКУД": (7, 7, "ОКУД: 7 цифр — код формы документа"),
    "ОКПО": (8, 10, "ОКПО: 8 или 10 цифр"),
    "РН ККТ": (14, 14, "РН ККТ: 14 цифр"),
    "ФН": (16, 16, "ФН: 16 цифр"),
    "ФПД": (10, 10, "ФПД: 10 цифр"),
}

# Начало штрих-кода — страна регистрации изготовителя (GS1).
BARCODE_COUNTRIES = (
    ("460", "Россия"), ("461", "Россия"), ("462", "Россия"), ("463", "Россия"),
    ("464", "Россия"), ("465", "Россия"), ("466", "Россия"), ("467", "Россия"),
    ("468", "Россия"), ("469", "Россия"), ("487", "Казахстан"), ("481", "Беларусь"),
    ("482", "Украина"), ("484", "Молдова"), ("470", "Киргизия"), ("476", "Азербайджан"),
    ("00", "США или Канада"), ("40", "Германия"), ("50", "Великобритания"),
)


def digits_only(value):
    return re.sub(r"\D", "", value or "")


def inn_valid(value):
    """Контрольные разряды ИНН (10 или 12 цифр)."""
    digits = digits_only(value)
    if len(digits) == 10:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        total = sum(int(symbol) * weight for symbol, weight in zip(digits, weights))
        return (total % 11) % 10 == int(digits[9])
    if len(digits) == 12:
        first = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        second = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        check_first = (sum(int(s) * w for s, w in zip(digits, first)) % 11) % 10
        check_second = (sum(int(s) * w for s, w in zip(digits, second)) % 11) % 10
        return check_first == int(digits[10]) and check_second == int(digits[11])
    return False


def ogrn_valid(value):
    """ОГРН (13) и ОГРНИП (15): последний разряд — остаток деления на 11 (13)."""
    digits = digits_only(value)
    if len(digits) == 13:
        return int(digits[:12]) % 11 % 10 == int(digits[12])
    if len(digits) == 15:
        return int(digits[:14]) % 13 % 10 == int(digits[14])
    return False


def snils_valid(value):
    """СНИЛС: сумма первых девяти цифр с весами 9…1, затем правило 100/101."""
    digits = digits_only(value)
    if len(digits) != 11:
        return False
    total = sum(int(symbol) * weight for symbol, weight in zip(digits[:9], range(9, 0, -1)))
    if total < 100:
        check = total
    elif total in (100, 101):
        check = 0
    else:
        check = total % 101
        if check == 100:
            check = 0
    return check == int(digits[9:11])


def kpp_valid(value):
    return bool(re.fullmatch(r"\d{4}[0-9A-Z]{2}\d{3}", (value or "").strip().upper()))


def bik_valid(value):
    digits = digits_only(value)
    return len(digits) == 9 and digits.startswith("04")


def format_valid(name, value):
    limits = FORMATS.get(name)
    if not limits:
        return None
    return limits[0] <= len(digits_only(value)) <= limits[1]


def okud_codes(path=OKUD_PATH):
    """Официальный классификатор ОКУД: {код: название формы}, источник."""
    if not os.path.exists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        source = "%s, %s" % (data.get("source", "ОК 011-93"), data.get("edition", ""))
        return data.get("codes", {}), source
    except Exception:      # noqa: BLE001
        return {}, ""


def okud_meaning(value):
    codes, source = okud_codes()
    digits = digits_only(value)
    if not codes:
        return "НЕ ЗНАЮ — классификатор ОКУД не найден"
    if digits in codes:
        return "%s · источник: %s" % (codes[digits], source)
    return "такого кода в ОКУД нет (источник: %s)" % source


def meaning(name, value):
    """Что код означает — только по источнику, иначе честное «НЕ ЗНАЮ»."""
    if name == "ОКУД":
        return okud_meaning(value)
    known = {
        "СНИЛС": "страховой номер индивидуального лицевого счёта (СФР)",
        "ИНН": "идентификационный номер налогоплательщика",
        "ОГРН": "номер записи о регистрации в ЕГРЮЛ",
        "ОГРНИП": "номер записи о регистрации в ЕГРИП",
        "КПП": "код причины постановки на учёт (9 знаков: код налоговой + причина)",
        "БИК": "банковский идентификационный код",
    }
    return known.get(name, "НЕ ЗНАЮ — нужен официальный справочник по этому коду")


def check_code(name, value):
    """Вердикт по одному коду: проверка, надёжность, смысл."""
    name = (name or "").upper()
    result = {"code": name, "value": (value or "").strip(),
              "digits": len(digits_only(value)),
              "about": FORMATS.get(name, ("", "", "неизвестный код"))[2]}
    if name == "ИНН":
        good = inn_valid(value)
        result["verdict"] = "контрольный разряд верный" if good else "контрольный разряд НЕ сходится"
        result["reliable"] = True
    elif name == "СНИЛС":
        good = snils_valid(value)
        result["verdict"] = "контрольное число верное" if good else "контрольное число НЕ сходится"
        result["reliable"] = True
    elif name in ("ОГРН", "ОГРНИП"):
        good = ogrn_valid(value)
        result["verdict"] = "контрольный разряд верный" if good else "контрольный разряд НЕ сходится"
        result["reliable"] = True
    elif name == "КПП":
        good = kpp_valid(value)
        result["verdict"] = "формат верный" if good else "формат НЕ верный"
        result["reliable"] = False
    elif name == "БИК":
        good = bik_valid(value)
        result["verdict"] = "формат верный" if good else "формат НЕ верный"
        result["reliable"] = False
    else:
        good = format_valid(name, value)
        result["verdict"] = ("формат верный, значение не сверено" if good
                             else "формат НЕ верный")
        result["reliable"] = False
    result["meaning"] = meaning(name, value)
    return result


CODE_LABELS = (
    ("ИНН", r"(?i)\bИНН[^\d]{0,6}(\d{10}|\d{12})"),
    ("СНИЛС", r"(?i)\bСНИЛС[^\d]{0,6}(\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2})"),
    ("ОГРНИП", r"(?i)\bОГРНИП[^\d]{0,6}(\d{15})"),
    ("ОГРН", r"(?i)\bОГРН[^\d]{0,6}(\d{13})"),
    ("КПП", r"(?i)\bКПП[^\w]{0,6}(\d{4}[0-9A-Za-z]{2}\d{3})"),
    ("БИК", r"(?i)\bБИК[^\d]{0,6}(\d{9})"),
    ("ОКУД", r"(?i)\bОКУД[^\d]{0,6}(\d{7})"),
    ("ОКПО", r"(?i)\bОКПО[^\d]{0,6}(\d{8}|\d{10})"),
    ("РН ККТ", r"(?i)\bРН\s?ККТ[^\d]{0,6}(\d{14})"),
    ("ФН", r"(?i)\bФН[^\d]{0,6}(\d{16})"),
    ("ФПД", r"(?i)\bФПД[^\d]{0,6}(\d{10})"),
)


def find_labeled_codes(text):
    """Коды, подписанные в тексте: «ИНН 7707083893», «ОКУД 0310001»."""
    found = []
    for name, pattern in CODE_LABELS:
        for match in re.finditer(pattern, text or ""):
            found.append((name, match.group(1)))
    return found


def check_text(text):
    """Все подписанные коды из текста с вердиктами."""
    results, seen = [], set()
    for name, value in find_labeled_codes(text):
        key = (name, digits_only(value))
        if key in seen:
            continue
        seen.add(key)
        results.append(check_code(name, value))
    return results


def barcode_country(value):
    """Страна изготовителя по началу штрих-кода."""
    digits = digits_only(value)
    for prefix, country in BARCODE_COUNTRIES:
        if digits.startswith(prefix):
            return country
    return ""


def _decode_image(image):
    """QR и штрих-коды на одном изображении (zxing-cpp, запасной путь — OpenCV)."""
    found = []
    try:
        import zxingcpp
    except Exception:      # noqa: BLE001
        zxingcpp = None
    if zxingcpp is not None:
        try:
            for result in zxingcpp.read_barcodes(image):
                if result.text:
                    item = {"format": str(result.format).split(".")[-1],
                            "text": result.text.strip()}
                    if item not in found:
                        found.append(item)
        except Exception:      # noqa: BLE001
            pass
    if found:
        return found
    try:
        import cv2
        detector = cv2.QRCodeDetector()
        for turn in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180,
                     cv2.ROTATE_90_COUNTERCLOCKWISE):
            working = image if turn is None else cv2.rotate(image, turn)
            data, _, _ = detector.detectAndDecode(working)
            if data and data.strip():
                found.append({"format": "QR", "text": data.strip()})
                break
    except Exception:      # noqa: BLE001
        pass
    return found


def find_codes(path, max_pages=6):
    """Коды на снимке или на страницах PDF: [{'format': 'QR', 'text': '…'}]."""
    try:
        import cv2
        import numpy as np
    except Exception:      # noqa: BLE001
        return []
    payloads = []
    try:
        if str(path).lower().endswith(".pdf"):
            import pymupdf
            document = pymupdf.open(path)
            try:
                for number in range(1, min(len(document), max_pages) + 1):
                    payloads.append(document[number - 1]
                                    .get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
                                    .tobytes("png"))
            finally:
                document.close()
        else:
            with open(path, "rb") as handle:
                payloads.append(handle.read())
        found = []
        for payload in payloads:
            image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue
            for item in _decode_image(image):
                if item not in found:
                    found.append(item)
        return found
    except Exception:      # noqa: BLE001
        return []


def parse_codes(codes):
    """Коды → поля документа: QR (Wi-Fi или ссылка) и штрих-код (страна)."""
    fields = []
    for item in codes:
        fmt = item.get("format", "QR")
        text = (item.get("text") or "").strip()
        if not text:
            continue
        fields.append({"field": "Код (%s)" % fmt, "value": text[:200], "page": 1,
                       "line": 1, "how": "расшифровка кода (zxing-cpp)"})
        if fmt.upper().startswith(("QR", "DATA_MATRIX", "DATAMATRIX", "AZTEC", "PDF417")):
            if text.lower().startswith("wifi:"):
                parts = {}
                for chunk in text[5:].split(";"):
                    if ":" in chunk:
                        key, value = chunk.split(":", 1)
                        parts[key.upper()] = value
                if parts.get("S"):
                    fields.append({"field": "имя сети Wi-Fi (из QR)", "value": parts["S"],
                                   "page": 1, "line": 1, "how": "QR, формат Wi-Fi"})
                if parts.get("P"):
                    fields.append({"field": "пароль Wi-Fi (из QR)", "value": parts["P"],
                                   "page": 1, "line": 1, "how": "QR, формат Wi-Fi"})
                if parts.get("T"):
                    fields.append({"field": "защита сети (из QR)", "value": parts["T"],
                                   "page": 1, "line": 1, "how": "QR, формат Wi-Fi"})
            elif text.lower().startswith(("http://", "https://", "www.")):
                fields.append({"field": "QR ведёт на адрес", "value": text, "page": 1,
                               "line": 1, "how": "ссылка из QR-кода"})
        else:
            country = barcode_country(text)
            if country:
                fields.append({"field": "Страна по штрих-коду", "value": country,
                               "page": 1, "line": 1, "how": "начало штрих-кода (GS1)"})
    return fields


if __name__ == "__main__":
    print("самопроверка кодов")
    print("  ИНН 7707083893:", "верный" if inn_valid("7707083893") else "НЕ верный")
    print("  ИНН 7707083894:", "верный" if inn_valid("7707083894") else "НЕ верный")
    print("  ОГРН 1027700132195:", "верный" if ogrn_valid("1027700132195") else "НЕ верный")
    print("  СНИЛС 112-233-445 95:", "верный" if snils_valid("11223344595") else "НЕ верный")
    print("  ОКУД 0310001 →", okud_meaning("0310001"))
    for item in check_text("ИНН 7707083893, ОКУД 0310001, КПП 773601001"):
        print("  %-6s %-12s %s" % (item["code"], item["value"], item["verdict"]))
