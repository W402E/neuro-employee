# -*- coding: utf-8 -*-
r"""CORE — смысловая часть продукта: база знаний, поиск, ответ модели, поля документа.
English identifiers (требование куратора 23.11.2026); русский текст — только в сообщениях.

Правило дома: **модель предлагает — правило решает**. Все числа (сроки, количество полей,
проверка «нет ли чисел вне базы») считает код, а не модель.
"""
import json
import os
import re
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: BLE001
    pass

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.join(MODULE_DIR, "data", "knowledge_base.json")
ENGINE_URL = "http://127.0.0.1:11434"
TEXT_MODEL = "qwen2.5:3b"
VECTOR_MODEL = "bge-m3"


# ---------------------------------------------------------------------------------- база знаний
def load_base(path=BASE_PATH):
    """Прочитать базу знаний: список записей {document, clause, text}."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return data.get("records", [])
    return data


def stem_words(text):
    """Основы слов: «каналов» и «каналы» дают одну основу."""
    words = re.findall(r"[a-zа-яё0-9\-]{3,}", (text or "").lower())
    return {word[:5] if len(word) >= 6 else word for word in words}


def embed(text, model=VECTOR_MODEL, engine=ENGINE_URL):
    """Текст → вектор длины 1 (Ollama, локально)."""
    body = json.dumps({"model": model, "input": [text], "keep_alive": "30m"},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(engine + "/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        vector = json.loads(response.read().decode("utf-8"))["embeddings"][0]
    length = sum(value * value for value in vector) ** 0.5 + 1e-9
    return [value / length for value in vector]


def search_base(question, records, limit=4, engine=ENGINE_URL):
    """Поиск: смысл + общие слова. Не больше двух пунктов из одного документа."""
    question_vector = embed(question, engine=engine)
    question_words = stem_words(question)
    scored = []
    for record in records:
        meaning = sum(a * b for a, b in zip(embed(record["text"], engine=engine),
                                            question_vector))
        overlap = (len(question_words & stem_words(record["text"]))
                   / max(1, len(question_words)))
        scored.append({"score": meaning + 0.6 * overlap, **record})
    scored.sort(key=lambda item: -item["score"])
    per_document, chosen = {}, []
    for item in scored:
        name = item["document"]
        if per_document.get(name, 0) >= 2:
            continue
        per_document[name] = per_document.get(name, 0) + 1
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def ask_model(system, user, model=TEXT_MODEL, engine=ENGINE_URL, limit=220):
    """Запрос к языковой модели (Ollama)."""
    body = json.dumps({"model": model,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "stream": False, "keep_alive": "30m",
                       "options": {"temperature": 0.2, "num_predict": limit, "num_ctx": 4096}},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(engine + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=900) as response:
        return json.loads(response.read().decode("utf-8"))["message"]["content"].strip()


def _numbers(text):
    return {value.rstrip(".,") for value in re.findall(r"\d+(?:[.,]\d+)*", text or "")}


def answer_by_laws(question, base_path=BASE_PATH, engine=ENGINE_URL):
    """Ответ по базе законов + проверка правилом. Возвращает словарь для интерфейса."""
    records = load_base(base_path)
    matches = search_base(question, records, 4, engine)
    system = ("Ты — помощник обслуживающей организации. Отвечай ТОЛЬКО по фрагментам закона, "
              "которые тебе дали. Если ответа нет — напиши: В базе нет ответа. "
              "Числа переноси дословно.")
    fragments = "\n\n".join("[Ф%d] %s, %s:\n%s" % (number + 1, item["document"],
                                                  item["clause"], item["text"])
                            for number, item in enumerate(matches))
    request = ("Фрагменты закона:\n\n%s\n\nВопрос: %s\n\n"
               "Ответь прямо на вопрос одним-двумя предложениями. "
               "Последней строкой напиши: Источник: <документ, пункт>" % (fragments, question))
    raw = ask_model(system, request, engine=engine)

    answer, source = raw, ""
    found = re.search(r"источник\s*:", raw, re.IGNORECASE)
    if found:
        answer = raw[:found.start()].strip()
        tail = raw[found.end():].strip()
        source = tail.splitlines()[0].strip() if tail else ""
    numbers_base = set()
    for item in matches:
        numbers_base |= _numbers(item["text"]) | _numbers(item["document"]) | _numbers(item["clause"])
    outside = sorted(_numbers(answer) - _numbers(question) - numbers_base)
    refusal = bool(re.search(r"(нет ответа|не соответствует|в базе нет|нет сведений)",
                             answer, re.IGNORECASE))
    return {"question": question, "answer": answer, "source": source,
            "source_ok": bool(re.search(r"п\.\s?\d|ст\.\s?\d", source)),
            "refusal": refusal, "numbers_outside": outside, "matches": matches}


# ---------------------------------------------------------------------------------- вид документа
DOCUMENT_TYPES = (
    ("заявление", ("прошу", "заявител")),
    ("билет, талон или проездной", ("билет", "проездной", "талон", "льготн", "рейс",
                                     "посадочный", "контролёр", "контролер")),
    ("квитанция за услуги (ЖКХ)", ("лицевой счёт", "лицевой счет", "лицевого счёта",
                                   "оплатить до", "расчёты за", "расчеты за", "к оплате:")),
    ("счёт или счёт-фактура", ("счёт-фактура", "счет-фактура", "итого к оплате",
                                "оплатите счет", "оплатите счёт", "получатель платежа",
                                "назначение платежа", "счёт на оплату", "счет на оплату",
                                "счёт №", "счет №", "счёт-договор", "р/с:", "р/с ",
                                "расчётный счёт", "к/с:")),
    ("накладная", ("накладная", "поставщик", "грузополучател", "товарная накладн")),
    ("чек или квитанция об оплате", ("чек", "сумма", "комиссия", "квитанц")),
    ("ценник или ярлык", ("ценник", "цена", "штрих")),
    ("наклейка на оборудовании", ("s/n", "mac:", "wi-fi", "пароль")),
    ("отчёт или таблица показателей", ("показател", "наименование мероприяти", "за 20")),
    ("реклама или тариф", ("руб/мес", "мб/с", "мбит/с", "подключи")),
    ("акт или протокол проверки", ("акт ", "протокол", "заключение")),
)

ROUTES = {
    "заявление": ("Журнал обращений", "зарегистрировать, посчитать срок ответа, поставить на контроль",
                  "дата, номер, адрес, заявитель"),
    "чек или квитанция об оплате": ("Журнал оплат", "отнести к оплате по объекту и сверить с начислением",
                                    "дата, сумма, получатель, назначение платежа"),
    "билет, талон или проездной": ("Журнал поездок или подотчёт",
                                    "отнести к расходам, сверить маршрут и дату",
                                    "дата, маршрут, стоимость"),
    "квитанция за услуги (ЖКХ)": ("Журнал оплат по лицевому счёту",
                                  "сверить период и сумму, отнести к лицевому счёту квартиры",
                                  "лицевой счёт, период, сумма, адрес"),
    "счёт или счёт-фактура": ("Журнал оплат или бухгалтерия",
                             "сверить реквизиты и сумму, отправить на оплату, подшить к договору",
                             "дата, сумма, получатель, назначение платежа, ИНН, КПП"),
    "накладная": ("Склад или журнал поставок", "оприходовать по позициям, сверить количество и сумму",
                  "номер, дата, поставщик, получатель, сумма"),
    "наклейка на оборудовании": ("Реестр оборудования", "внести устройство с MAC и серийным номером на учёт",
                                 "MAC, серийный номер"),
    "ценник или ярлык": ("Прайс или опись товаров", "сверить цену на полке с прайсом",
                         "наименование, цена"),
    "акт или протокол проверки": ("Журнал проверок", "подшить к объекту, следить за сроком следующей проверки",
                                  "дата, объект, результат, срок"),
    "реклама или тариф": ("Не в учёт", "это не документ для учёта — только для сведения", "—"),
    "отчёт или таблица показателей": ("Архив отчётов", "подшить к периоду, сравнить с прошлым периодом",
                                      "период, организатор, показатели"),
    "не распознан": ("Не определено", "посмотреть глазами и уточнить, что это за документ", "—"),
}


def document_type(text):
    """Что это за документ — по словам документа."""
    low = (text or "").lower()
    for name, markers in DOCUMENT_TYPES:
        if any(marker in low for marker in markers):
            return name
    return "не распознан"


# ---------------------------------------------------------------------------------- поля документа
LABEL_RULES = [
    ("вид документа", r"(?i)(АКТ[^\n]{0,60})"),
    ("номер документа", r"(?i)(?:№|N)\s*([\w\-/]{2,20})"),
    ("дата", r"(?i)\b(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})\b"),
    ("объект", r"(?i)(?:объект|адрес)[^\n]{0,60}?([А-ЯЁ][^\n]{3,80})"),
    ("адрес", r"(?i)(?:адрес|объект)[^\n]{0,20}?((?:ул|улица|просп|пер|д)\.?[^\n]{3,70})"),
    ("заявитель", r"(?i)(?:заявител\w*|от кого|фио)[^\n]{0,15}([А-ЯЁ][а-яё]+\s[А-ЯЁ]\.\s?[А-ЯЁ]?\.?)"),
    ("организация", r"(?i)((?:ООО|АО|ПАО|МУП|ТСЖ|УК)\s*[«\"]?[А-ЯЁ][^\n,]{2,40})"),
    ("телефон", r"(\+?[78][\d\s\-()]{9,16})"),
    ("количество каналов", r"(?i)(\d{1,3})\s*(?:дымов|вентиляционн|канал)"),
    ("проверяющая организация", r"(?i)проверяющ\w* организаци\w*[^\n]{0,10}([А-ЯЁ][^\n,]{2,40})"),
    ("срок поверки прибора", r"(?i)поверк\w*[^\n]{0,40}?(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
]

# Сумма: «12 300,00», «4500.00», «12300» — но не «12» от «12 300,00».
MONEY = r"(\d{1,3}(?:\s?\d{3})+(?:[.,]\d{2})|\d+[.,]\d{2}|\d{3,})"
# Название организации: только целым словом, без хвоста предложения.
ORG = r"(?<![А-ЯЁа-яё])((?:ООО|АО|ПАО|ЗАО|ИП|МУП|ГУП|Филиал)\s*[«\"]?[^\n,;.]{2,60})"

CONTEXT_RULES = {
    "билет, талон или проездной": [
        ("номер билета", r"(?i)билет\w*[^\d\n]{0,30}?(\d{10,20})"),
        ("номер заказа", r"(?i)заказ\w*[^\d\n]{0,30}?(\d{8,20})"),
        ("код льготы", r"(?i)код льготы[^\d]{0,20}(\d{2,6})"),
        ("пассажиров", r"(?i)пассажиров[^\d]{0,12}(\d{1,2})"),
        ("время", r"\b(\d{1,2}:\d{2})\b"),
    ],
    "квитанция за услуги (ЖКХ)": [
        ("лицевой счёт", r"(?i)лицев\w*\s*сч[её]т\s*:?\s*(\d{6,20})"),

        ("телефон", r"(?i)телефон\s*:?\s*(\+?[\d\s\-()]{10,20})"),
        ("адрес", r"(?i)адрес\s*:?\s*([А-ЯЁа-яё0-9][^\n]{4,80})"),
        ("номер счёта", r"(?i)сч[её]т\s*№?\s*(\d{6,12})"),
        ("дата формирования", r"(?i)дата формирования[^\d]{0,20}(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        ("оплатить до", r"(?i)оплатить до\s*:?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        ("к оплате", r"(?i)к оплате\s*:?\s*" + MONEY + r"\s*руб"),
        ("период расчётов", r"(?i)(?:расч[её]ты|начислено)\s+за\s+([А-ЯЁа-яё]+\s*\d{4})"),
        ("назначение платежа", r"(?i)(?:расч[её]ты|начислени\w*)\s+(за\s+[А-ЯЁа-яё]+\s*\d{4})"),
        ("ИНН", r"(?i)ИНН[^\d]{0,10}(\d{10}|\d{12})"),
        ("КПП", r"(?i)КПП[^\d]{0,10}(?:\d{10,12}\s*/\s*)?(\d{9})"),
        ("к оплате (руб коп)", r"(?i)к оплате\s*:?\s*(\d[\d\s]{0,9})\s*руб"),
        ("сумма в рублях", r"(?<![\d.,])" + MONEY + r"\s*руб"),
    ],
    "счёт или счёт-фактура": [
        ("номер счёта", r"(?i)сч[её]т\w*[^\n]{0,30}?№\s*([\dА-ЯЁA-Z\-/]{1,20})"),
        ("дата", r"(?i)\b(\d{2}[.\-/]\d{2}[.\-/]\d{2,4}|\d{4}-\d{2}-\d{2})\b"),
        ("заезд", r"(?i)заезд\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        ("выезд", r"(?i)выезд\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        ("плательщик", r"(?i)плательщик\s*:?\s*([А-ЯЁ][А-ЯЁа-яё\s\-]{3,50})"),
        ("получатель платежа",
         r"(?i)((?:ООО|АО|ПАО|ИП)\s*[«\"]?[^()\n]{2,50}?)\s*\(\s*организация получатель"),
        ("получатель платежа", r"(?i)получатель платежа\s*:?\s*([А-ЯЁ«\"][^\n,]{2,60})"),
        ("наименование банка", r"(?i)наименование банка\s*:?\s*([А-ЯЁ][^\n,]{3,60})"),
        ("сумма к оплате", r"(?i)(?:итого|всего|к оплате|сумма|стоимость|цена)[^\d]{0,25}" + MONEY),
        ("сумма прописью в рублях", r"(?i)сумм\w*\s*(\d[\d\s]{0,9})\s*руб"),
        ("поставщик или исполнитель", r"(?i)(?:поставщик|исполнитель|продавец|получатель счёта)"
                                      r"\s*:?\s*" + ORG),
        ("ИНН", r"(?i)ИНН[^\d]{0,8}(\d[\d\s]{8,14}\d)"),
        ("КПП", r"(?i)КПП[^\w]{0,8}(\d{4}[\w]{2}\d{3})"),
        ("БИК", r"(?i)БИК[^\d]{0,8}(\d[\d\s]{7,9}\d)"),
        ("расчётный счёт", r"(?i)(?:р/с|расч[её]тный сч[её]т)[^\d]{0,10}(\d[\d\s]{18,24}\d)"),
        ("назначение платежа", r"(?i)назначение платежа\s*:?\s*([А-ЯЁа-яё][^\n]{3,80})"),
    ],
    "чек или квитанция об оплате": [
        ("дата", r"(?i)\b(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})\b"),
        ("сумма", r"(?i)сумм\w*[^\d]{0,15}(\d+[.,]\d{2})"),
        ("получатель", r"(?i)(?:пао|ао|ооо|ип)\s+([А-ЯЁA-Z][^\n,]{2,40})"),
        ("кассир", r"(?i)кассир[^\w]{0,4}([А-ЯЁ][а-яё\-]{2,20})"),
        ("маршрут", r"(?i)марш\w*[^\d]{0,12}(\d{1,4})"),
        ("остановка", r"(?i)остановка[^\w]{0,4}([А-ЯЁ][А-ЯЁа-яё\- ]{2,30})"),
        ("время", r"\b(\d{1,2}:\d{2})\b"),
    ],
    "наклейка на оборудовании": [
        ("MAC-адрес", r"(?i)mac[^\w]{0,3}((?:[0-9A-F]{2}:){5}[0-9A-F]{2})"),
        ("серийный номер", r"(?i)(?:s/n|serial)[^\w]{0,3}([A-Za-z0-9\-]{6,})"),
        ("имя сети Wi-Fi", r"(?i)(?:wifi|wi-fi|ssid)[^\n]{0,20}?([A-Za-z0-9А-ЯЁ\-_]{4,32})"),
        ("адрес веб-интерфейса", r"(?i)((?:https?://)?\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"),
    ],
    "накладная": [
        ("номер", r"(?i)(?:накладн\w*|№)\s*[№:]?\s*([\dА-ЯЁA-Z\-/]{1,20})"),
        ("дата", r"(?i)\b(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})\b"),
        ("поставщик", r"(?i)поставщик[^\n]{0,10}" + ORG),
        ("сумма", r"(?i)(?:итого|всего|сумма)[^\d]{0,15}(\d+[.,]\d{2})"),
    ],
}

GUESSES = (
    ("предположительно ссылка", r"(?i)\b((?:https?://|www\.)[^\s,;]+)"),
    ("предположительно MAC-адрес", r"(?i)\b((?:[0-9A-F]{2}[:\-]){5}[0-9A-F]{2})\b"),
    ("предположительно IP-адрес", r"\b(\d{1,3}(?:\.\d{1,3}){3})\b"),
    ("предположительно телефон", r"(?<![А-ЯЁа-яёA-Za-z:№])(\+?[78][\d\s\-()]{9,14})(?![\d])"),
    ("предположительно сумма", r"\b(\d(?:[\d\s]{0,8})\d[.,]\d{2})(?![\d])(?!\.[\d])"),
    ("предположительно дата", r"\b(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})\b"),
)


# Подписи, после которых стоит значение: «Сумма: 100,00», «Получатель — ООО …», «Итого к оплате».
# Работают для любого вида документа — после точных правил, чтобы не мешать им.

LABEL_VALUE_RULES = [
    ("сумма к оплате", r"(?i)(?:итого\s*(?:к\s*оплате)?|всего\s*к\s*оплате|сумма\s*(?:к\s*оплате)?|"
                       r"стоимость|цена)\s*[:№\-]?\s*" + MONEY),
    ("сумма в рублях", r"(?<![\d.,])" + MONEY + r"\s*(?:руб|₽|RUB)"),
    ("получатель", r"(?i)(?:получатель|поставщик|исполнитель|продавец|контрагент)"
                   r"\s*[:№\-]?\s*[^\n]{0,3}?" + ORG),
    ("назначение платежа", r"(?i)назначени\w*\s*(?:платежа)?\s*[:\-]?\s*([А-ЯЁа-яё0-9][^\n]{3,90})"),
    ("номер документа", r"(?i)(?:сч[её]т|договор|акт|накладн\w*)\s*[^\d\n]{0,15}?"
                        r"№\s*([\dА-ЯЁA-Z\-/]{1,20})"),
    ("дата документа", r"(?i)(?:от|дата)\s*[:.]?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
]


def label_value_fields(pages, существующие, limit=12):
    """Поля по подписям «подпись: значение» — для любого вида документа."""
    найдено = []
    известные_имена = {item["field"] for item in существующие}
    for page in pages:
        for name, pattern in LABEL_VALUE_RULES:
            if name in известные_имена and len(найдено) >= limit:
                break
            for match in re.finditer(pattern, page["text"]):
                value = (match.group(1) or "").strip(" .,:;№-")
                value = re.split(r"\.\s*(?=Дата|От|Итого|Сумма)|;\s*(?=Итого|Дата)",
                                 value)[0].strip(" .,:;-")
                if len(value) < 2:
                    continue
                line_number = page["text"][:match.start()].count("\n") + 1
                item = {"field": name, "value": value[:110], "page": page["page"],
                        "line": line_number, "how": "подпись: " + name}
                # такое же значение уже есть под другим именем — не дублируем
                if any(other["value"].strip() == value.strip() for other in найдено):
                    continue
                if item not in найдено and len(найдено) < limit:
                    найдено.append(item)
    return найдено


# Правила, которым нужен текст страницы целиком: значение и подпись бывают на разных строках.
MULTILINE_RULES = {
    "квитанция за услуги (ЖКХ)": [
        ("лицевой счёт", r"(?i)(\d{10,14})\s*\n?\s*лицев\w*\s*сч[её]т"),
        ("телефон", r"(?i)(\+?[78][\d\s\-()]{9,16})\s*\n?\s*Телефон"),
    ],
    "билет, талон или проездной": [
        ("номер билета", r"(?i)электронный билет[^\n]*\n[^\n]*\n\s*(\d{10,20})"),
        ("дата отправления", r"(?is)(?:время отправления|отправлени\w*)[^\n]*\n[^\n]*\n"
                             r"[^\n]*?(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        ("дата и время оформления", r"(?is)оформлени\w*[^\n]*\n[^\n]*\n\s*"
                                    r"(\d{2}[.\-/]\d{2}[.\-/]\d{2,4})"),
        # строка маршрута: «19.10 07:28 ТУЛА 1 КУРСКАЯ -> МОСКВА КУРСКАЯ 19.10 10:01 3С»

        ("станция отправления", r"(?m)^\s*\d{2}\.\d{2}\s+\d{1,2}:\d{2}\s+"
                               r"([А-ЯЁ][А-ЯЁ0-9 \-]{2,40}?)\s*->"),
        ("станция прибытия", r"(?m)->\s*([А-ЯЁ][А-ЯЁ0-9 \-]{2,40}?)\s+"
                            r"\d{2}\.\d{2}\s+\d{1,2}:\d{2}"),
        ("дата и время отправления", r"(?m)^\s*(\d{2}\.\d{2}\s+\d{1,2}:\d{2})\s+[А-ЯЁ]"),
        ("дата и время прибытия", r"(?m)->\s*[А-ЯЁ][^\n]*?\s+(\d{2}\.\d{2}\s+\d{1,2}:\d{2})"),
        ("поезд", r"(?i)поезд\s*№?\s*(\d{2,5})"),
        ("вагон", r"(?i)вагон\s*№?\s*(\d{1,3})"),
        ("место", r"(?i)место\s*№?\s*(\d{1,4})"),
        ("тип места", r"\b(Сидячий|Сидячие|Плацкартный|Плацкартное|Купе|СВ|Люкс)\b"),
        ("класс обслуживания", r"(?m)\d{1,2}:\d{2}\s+(\d[А-ЯЁ])\s*$"),
        ("итого к оплате", r"(?is)итого[^\n]*\n[^\n]*\n\s*(\d[\d\s]{0,8}[.,]\d{2})"),
        ("НДС", r"(?i)НДС\s*(\d{1,2})\s*%"),
        ("тариф (билет / плацкарта)",
         r"(?i)тариф[^\n]*\n[^\n]*\n\s*(\d[\d\s]{0,8}[.,]\d{2}\s*/\s*\d[\d\s]{0,8}[.,]\d{2})"),
        ("цена по билету", r"(?i)цена[^\n]*\n[^\n]*\n\s*(\d[\d\s]{0,8}[.,]\d{2})"),
        ("перевозчик (ИНН)", r"(?i)перевозчик[^\n]*\n[^\n]*\n\s*([А-ЯЁ][^\n]{2,70})"),
        ("форма оплаты", r"(?i)форма оплаты[^\n]*\n[^\n]*\n\s*([А-ЯЁа-яё][^\n]{2,30})"),
        ("номер заказа", r"(?i)номер заказа[^\n]*\n[^\n]*\n\s*(\d{10,20})"),
        ("пассажир", r"(?m)^([А-ЯЁ]{3,}\s+[А-ЯЁ]\.\s?[А-ЯЁ]?\.?)\s*$"),
        ("СНИЛС (в маске)", r"(?i)снилс[^\n]{0,24}"
                            r"([\d*]{4}[-\s]?[\d*]{4}[-\s]?[\d*]{2,4}[\s]?\d{2})"),
    ],
    "счёт или счёт-фактура": [
        ("получатель платежа",
         r"(?i)((?:ООО|АО|ПАО|ИП|Филиал)[^\n]{0,60}?)\s*\n?\s*\(\s*организация\s+получатель"),
    ],
    "наклейка на оборудовании": [
        ("пароль", r"(?i)парол\w*\s*[:\-]?\s*([A-Za-z0-9\-_!@#]{4,32})"),
    ],
}


def extract_fields(pages, doc_type, limit=40):
    """Поля правилами: сначала правила через строку, потом правила вида, потом общие."""
    rules = CONTEXT_RULES.get(doc_type) or LABEL_RULES
    found = []
    for page in pages:
        for name, pattern in MULTILINE_RULES.get(doc_type, []):
            for match in re.finditer(pattern, page["text"]):
                value = (match.group(1) or "").strip(" .,;")
                if not value:
                    continue
                line_number = page["text"][:match.start()].count("\n") + 1
                found.append({"field": name, "value": value[:80], "page": page["page"],
                              "line": line_number, "how": "правило (через строку): " + name})
                if len(found) >= limit:
                    return found
        for line_number, line in enumerate(page["text"].splitlines(), 1):
            for name, pattern in rules:
                for match in re.finditer(pattern, line):
                    value = match.group(1).strip()
                    if not value:
                        continue
                    if sum(1 for item in found if item["field"] == name) >= 2:
                        continue
                    found.append({"field": name, "value": value, "page": page["page"],
                                  "line": line_number, "how": "правило: " + name})
                    if len(found) >= limit:
                        return found
    # Общий проход по подписям: добираем то, что точные правила не поймали.
    if doc_type != "билет, талон или проездной":
        добор = label_value_fields(pages, found)
        имена_есть = {item["field"] for item in found}
        for item in добор:
            if item["field"] not in имена_есть:
                found.append(item)
                имена_есть.add(item["field"])

    # Билет со стоимостью 0 — вероятно льготный: пишем словами, а не молчим.
    if doc_type == "билет, талон или проездной":
        откуда = next((item["value"] for item in found
                       if "станция отправления" in item["field"].lower()), "")
        куда = next((item["value"] for item in found
                     if "станция прибытия" in item["field"].lower()), "")
        if откуда and куда:
            found.insert(0, {"field": "маршрут", "value": "%s → %s" % (откуда, куда),
                             "page": 1, "line": 1, "how": "собрано правилом из станций"})
        else:
            текст_страниц = " ".join(page["text"] for page in pages).lower()
            if "маршрут" in текст_страниц:
                found.append({"field": "маршрут (пояснение)",
                              "value": "названия станций в текстовом слое отсутствуют — "
                                       "они в картинке или штрихкоде",
                              "page": 1, "line": 1, "how": "вывод правила (не модель)"})
        цена = [item["value"] for item in found if "цена" in item["field"].lower()]
        тариф = [item["value"] for item in found if "тариф" in item["field"].lower()]
        ноль = all(str(значение).replace(" ", "").split("/")[0].startswith(("0,", "0."))
                   for значение in цена) if цена else False
        if ноль:
            пояснение = "цена 0"
            if тариф:
                пояснение += ", тариф " + str(тариф[0]).replace(" ", "")
            found.append({"field": "льгота по билету",
                          "value": пояснение + " — билет льготный (плата не взимается)",
                          "page": 1, "line": 1, "how": "вывод правила (не модель)"})
    return found


BANK_MARKERS = ("инн", "кпп", "бик", "р/с", "к/с", "расчётный", "расчетный", "счёт",
                "счет", "заказ", "билет", "снилс", "номер заказа", "e-ticket")


def guess_fields(pages, existing, limit=8):
    """Значения, узнаваемые по виду (телефон, MAC, сумма…), с пометкой «предположительно»."""
    known = {item["value"] for item in existing}
    found = []
    for page in pages:
        lines = page["text"].splitlines()
        for line_number, line in enumerate(lines, 1):
            around = " ".join(lines[max(0, line_number - 3):line_number]).lower()
            is_bank_line = any(marker in around for marker in BANK_MARKERS)
            for name, pattern in GUESSES:
                for match in re.finditer(pattern, line):
                    value = match.group(1).strip(" .,;")
                    if len(value) < 4 or value in known:
                        continue
                    if name.endswith("телефон"):
                        only_digits = "".join(sign for sign in value if sign.isdigit())
                        if len(only_digits) > 11 or is_bank_line:
                            continue
                    if any(value in item or item in value for item in known):
                        continue
                    known.add(value)
                    found.append({"field": name, "value": value, "page": page["page"],
                                  "line": line_number, "how": "предположение по шаблону"})
                    if len(found) >= limit:
                        return found
    return found


# ---------------------------------------------------------------------------------- значимость (ПДн)
SENSITIVITY = {
    "пдн": {"label": "ПДн", "color": "#e83e8c",
            "about": "персональные данные: ФИО, адрес, телефон, паспорт, СНИЛС, ИНН, счёт"},
    "секрет": {"label": "секрет", "color": "#c62828",
               "about": "пароли, ПИН, CVV, коды доступа"},
    "оплата": {"label": "оплата", "color": "#1f5f9e",
               "about": "суммы, номера карт и операций"},
    "ключ": {"label": "API-ключ", "color": "#6a1b9a",
             "about": "ключи и токены доступа к сервисам"},
    "идентиф": {"label": "идентиф.", "color": "#333333",
                "about": "идентификаторы оборудования: MAC, IP, серийный номер, имя сети"},
}

BY_NAME = (
    ("нет", ("код (ean", "код (code", "штрихкод", "код (qr")),
    ("идентиф", ("mac-адрес", "ip-адрес", "серийный номер", "защита сети", "веб-интерфейс",
                 "имя сети")),
    ("секрет", ("пароль", "пин", "cvv", "код доступа")),
    ("ключ", ("api", "ключ", "токен", "token", "bearer", "secret")),
    ("оплата", ("сумма", "стоимость", "цена", "номер операции", "номер карт", "оплата")),
    ("пдн", ("фио", "фамили", "имя", "отчество", "адрес", "телефон", "паспорт", "снилс",
             "инн", "счёт", "счет", "заявител", "плательщик", "получатель физ")),
)

BY_VALUE = (
    ("секрет", r"(?i)wifi:.*;p:"),
    ("ключ", r"(?i)\b(?:sk-[A-Za-z0-9\-_]{10,}|Bearer\s+[A-Za-z0-9\-_.]{10,}|"
             r"(?:api[_\- ]?key|token)\s*[:=]\s*[A-Za-z0-9\-_.]{8,})"),
    ("пдн", r"\b\d{4}\s?\d{6}\b|\b\d{3}-\d{3}-\d{3}[ -]?\d{2}\b|\b\+?[78][\d\s\-()]{9,16}\b"),
    ("оплата", r"\b(?:\d{16}|\d{4}\s?\d{4}\s?\d{4}\s?\d{4})\b|\b\d+[.,]\d{2}\b"),
)


def sensitivity_of(field_name, value):
    """К какому классу значимости относится значение (пусто — не помечаем)."""
    low = (field_name or "").lower()
    for kind, markers in BY_NAME:
        if any(marker in low for marker in markers):
            return "" if kind == "нет" else kind
    for kind, pattern in BY_VALUE:
        if re.search(pattern, value or ""):
            return kind
    return ""


def mark_values(fields):
    """Каждому полю — класс, метка и цвет для рамки."""
    marked = []
    for item in fields:
        kind = item.get("kind") or sensitivity_of(item.get("field", ""), item.get("value", ""))
        entry = dict(item)
        if kind:
            entry["kind"] = kind
            entry["label"] = SENSITIVITY[kind]["label"]
            entry["color"] = SENSITIVITY[kind]["color"]
        marked.append(entry)
    return marked


def sensitivity_summary(fields):
    counts = {}
    for item in fields:
        kind = item.get("kind")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def mask_value(value, kind):
    """Значение под маску: оставляем намёк, а не данные."""
    text = str(value or "")
    if not text:
        return text
    if kind == "секрет" or len(text) <= 6:
        return "••••"
    return text[:3] + "…" + str(len(text)) + " знаков"


# ---------------------------------------------------------------------------------- карточка и бланк
# Как называются одни и те же обязательные поля в разных документах.
CARD_ALIASES = {
    "стоимость": ("тариф", "цена", "стоимост", "сумма"),
    "сумма": ("сумма", "тариф", "цена", "стоимост", "итого"),
    "дата": ("дата", "время"),
    "маршрут": ("маршрут", "откуда", "куда", "станц", "рейс"),
    "получатель": ("получатель", "поставщик", "исполнитель"),
    "номер": ("номер", "№"),
    "поставщик": ("поставщик", "исполнитель", "получатель"),
}


def _field_known(required, names):
    """Есть ли обязательное поле среди найденных — с учётом синонимов."""
    synonyms = CARD_ALIASES.get(required.lower(), (required.lower(),))
    return any(any(synonym in name.lower() for synonym in synonyms) for name in names)


def document_card(doc_type, fields, codes):
    """Смысловая карточка: что это, куда идёт в учёте, чего не хватает."""
    destination, action, required = ROUTES.get(doc_type, ROUTES["не распознан"])
    names = {item["field"] for item in fields}
    needed = [item for item in (required.split(", ") if required != "—" else []) if item]
    missing = [item for item in needed if not _field_known(item, names)]
    code_texts = []
    for item in codes or []:
        if isinstance(item, dict):
            code_texts.append("%s: %s" % (item.get("format", "код"), item.get("text", "")))
        else:
            code_texts.append(str(item))
    return {"destination": destination, "action": action, "required": required,
            "missing": missing, "codes": code_texts}


FORM_MARKERS = ("фио", "фамилия", "адрес", "дата", "номер", "прошу", "подпись", "заявител",
                "квартира", "помещение", "телефон", "сумма", "причина")


def empty_form(text, fields):
    """Пустой бланк: метки полей есть, а значений нет."""
    low = (text or "").lower()
    markers = [marker for marker in FORM_MARKERS if marker in low]
    return {"empty": len(markers) >= 2 and len(fields) == 0, "markers": markers,
            "values": len(fields)}


def build_act_text(fields, document_name="", masks=()):
    """Текст акта: штамп ПДн, значения (можно под маской), адреса полей."""
    from datetime import date
    counts = sensitivity_summary(fields)
    lines = ["АКТ ПРОВЕРКИ", "Дата составления: " + date.today().strftime("%d.%m.%Y"), "",
             "Разобрано автоматически, подтверждено человеком.", ""]
    if counts:
        composition = " · ".join("%s: %d" % (SENSITIVITY[kind]["label"], count)
                                  for kind, count in counts.items() if count)
        lines.append("НОСИТЕЛЬ ПЕРСОНАЛЬНЫХ ДАННЫХ И СЕКРЕТОВ (%s)." % composition)
        lines.append("Перед передачей за пределы контура значения с метками ПДн, секрет, "
                     "API-ключ, оплата удалить или обезличить (152-ФЗ, ст. 3, п. 9).")
        lines.append("")
    for item in fields:
        kind = item.get("kind") or sensitivity_of(item.get("field", ""), item.get("value", ""))
        value = item.get("value")
        if kind and kind in (masks or ()):
            value = mask_value(value, kind)
        label = (" [%s]" % SENSITIVITY[kind]["label"]) if kind else ""
        lines.append("%s: %s%s  (стр. %s, строка %s)"
                     % (item.get("field"), value, label, item.get("page"), item.get("line")))
    lines += ["", "Документ: " + (document_name or "без имени")]
    return "\n".join(lines)


if __name__ == "__main__":
    records = load_base()
    print("записей в базе:", len(records))
    print("документов:", len({item["document"] for item in records}))
    print("вид образца:", document_type("Прошу проверить вентиляционные каналы в МКД"))
    demo_fields = mark_values([
        {"field": "адрес", "value": "ул. Ленина, д. 5", "page": 1, "line": 3},
        {"field": "пароль Wi-Fi (из QR)", "value": "Ked6qAvyr8", "page": 1, "line": 1},
        {"field": "сумма", "value": "3040.00", "page": 1, "line": 11},
    ])
    print("значимость:", sensitivity_summary(demo_fields))
    print("карточка:", document_card("наклейка на оборудовании", demo_fields, []))
