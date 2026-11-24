# -*- coding: utf-8 -*-
r"""NEURO-EMPLOYEE — фронтенд на Streamlit (English identifiers, 23.11.2026).

Зачем этот файл: куратор вернул этап 4 на доработку с формулировкой «финальная версия проекта —
это полноценный продукт, который предоставляет пользователю возможность его использовать…
В Вашем случае используется только среда Google Colab». Его предложение — Streamlit.

Что делает приложение:
  * «Документ»: загрузить PDF/фото → прочитать (Тесект или текстовый слой) → определить вид
    документа → вытащить поля правилами → показать карточку «куда идёт в учёте» → рамки
    значимости (ПДн, секрет, оплата, API-ключ, идентиф.) → QR и штрих-коды → сверка кодов
    по классификаторам → оригинал рядом с полями.
  * «Вопрос по законам»: ответ по базе знаний со ссылкой на пункт и проверкой кодом.
  * «Сокращения»: библиотека с подсказками и добавлением своих значений.
  * «О приложении»: что умеет, чего не умеет, на чём работает.

Запуск локально:  streamlit run app.py
"""
import os
import sys
import tempfile

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import codes               # noqa: E402
import core                # noqa: E402
import glossary            # noqa: E402
import recognition         # noqa: E402

st.set_page_config(page_title="Нейро-сотрудник", page_icon="🏢", layout="wide")

QUESTION_EXAMPLES = (
    "Как часто проверяют дымовые и вентиляционные каналы в многоквартирном доме?",
    "Кто обеспечивает надлежащее содержание дымовых и вентиляционных каналов?",
    "Что указывают в акте обследования дымовых и вентиляционных каналов?",
    "Какие осмотры общего имущества бывают и когда проводятся текущие?",
    "Какая минимальная температура воздуха должна быть в квартире?",
)


# --------------------------------------------------------------------------------- утилиты экрана
def engine_available():
    """Есть ли локальный движок Ollama (на облаке его нет — это нормально)."""
    try:
        import urllib.request
        request = urllib.request.Request(core.ENGINE_URL + "/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except Exception:      # noqa: BLE001
        return False


def read_document(uploaded):
    """Прочитать загруженный файл: (pages, document_name, needs_ocr).

    pages = [{"page": 1, "text": "…"}] — так же, как в остальных модулях.
    """
    suffix = os.path.splitext(uploaded.name)[1].lower()
    handle, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(handle, "wb") as file_handle:
        file_handle.write(uploaded.getvalue())

    pages, needs_ocr = [], False
    if suffix == ".pdf":
        try:
            import pymupdf
            document = pymupdf.open(path)
            try:
                for number, sheet in enumerate(document, 1):
                    text = (sheet.get_text() or "").strip()
                    pages.append({"page": number, "text": text})
            finally:
                document.close()
            needs_ocr = sum(len(page["text"]) for page in pages) < 40
        except Exception:      # noqa: BLE001
            pages, needs_ocr = [], True
    else:
        pages, needs_ocr = [], True

    if needs_ocr:
        text, _ = recognition.read_page_best(path, 1)
        pages = [{"page": 1, "text": text}]
        needs_ocr = not text.strip()
    return pages, uploaded.name, needs_ocr, path


def preview_png(path):
    """Картинка оригинала для показа (PDF — первая страница)."""
    try:
        import cv2
        import numpy as np
        import pymupdf
        if str(path).lower().endswith(".pdf"):
            document = pymupdf.open(path)
            try:
                payload = document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).tobytes("png")
            finally:
                document.close()
        else:
            with open(path, "rb") as handle:
                payload = handle.read()
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        angle = recognition.orientation_angle(_png_on_disk(payload))
        if angle in (90, 180, 270):
            turns = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                     270: cv2.ROTATE_90_COUNTERCLOCKWISE}
            image = cv2.rotate(image, turns[angle])
        longest = max(image.shape[:2])
        if longest > 1400:
            factor = 1400 / longest
            image = cv2.resize(image, (int(image.shape[1] * factor), int(image.shape[0] * factor)))
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    except Exception:      # noqa: BLE001
        return None


def _png_on_disk(payload):
    handle, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(handle, "wb") as file_handle:
        file_handle.write(payload)
    return path


def badge(kind):
    """Метка значимости цветом (рамку рисуем вокруг значения в таблице)."""
    if not kind:
        return ""
    entry = core.SENSITIVITY.get(kind, {})
    return (":%s[**%s**]" % ("red" if kind == "секрет" else "violet", entry.get("label", "")))


# --------------------------------------------------------------------------------- вкладки
def tab_document():
    st.subheader("Документ")
    uploaded = st.file_uploader("Загрузите PDF или фото документа (JPG, PNG)",
                                type=["pdf", "jpg", "jpeg", "png", "tif", "tiff", "webp"])
    if not uploaded:
        st.info("Пока файла нет. Можно загрузить чек, наклейку роутера, заявление, накладную — "
                "приложение скажет, что это за документ, куда он идёт в учёте и какие поля нашлись.")
        return

    with st.spinner("Читаю документ…"):
        pages, name, needs_ocr, path = read_document(uploaded)
        full_text = "\n".join(page["text"] for page in pages)
        doc_type = core.document_type(full_text)
        fields = core.extract_fields(pages, doc_type)
        found_codes = codes.find_codes(path)
        fields += codes.parse_codes(found_codes)
        fields += core.guess_fields(pages, fields, limit=10 if not fields else 4)
        fields = core.mark_values(fields)
        card = core.document_card(doc_type, fields, found_codes)
        blank = core.empty_form(full_text, fields)
        checks = codes.check_text(full_text)
        abbreviations = glossary.find_in_text(full_text)

    left, right = st.columns((3, 2))

    with left:
        if needs_ocr:
            st.warning("В файле нет текстового слоя и Тесеракт не прочитал — проверьте снимок.")
        st.markdown("### Смысл документа")
        st.markdown("**Вид документа:** %s" % doc_type)
        st.markdown("**Куда идёт в учёте:** %s — %s" % (card["destination"], card["action"]))
        st.markdown("**Обязательно должно быть:** %s" % card["required"])
        if card["missing"]:
            st.error("Не хватает: %s" % ", ".join(card["missing"]))
        else:
            st.success("Всё обязательное на месте")
        if blank["empty"]:
            st.error("Похоже на **пустой бланк**: метки полей есть (%s), а значений нет."
                     % ", ".join(blank["markers"]))

        st.markdown("### Поля документа")
        masks = st.multiselect("Что заменить маской в акте и реестре:",
                               options=list(core.SENSITIVITY.keys()),
                               format_func=lambda key: core.SENSITIVITY[key]["label"],
                               default=["секрет", "ключ"])
        if fields:
            table = []
            for item in fields:
                table.append({
                    "Поле": ("[" + item.get("label", "") + "] " if item.get("label") else "") + item["field"],
                    "Значение": (core.mask_value(item["value"], item.get("kind"))
                                 if item.get("kind") in masks else item["value"]),
                    "Значимость": item.get("label", "—"),
                    "Где": "стр. %s, строка %s" % (item.get("page"), item.get("line")),
                    "Как найдено": item.get("how", ""),
                })
            st.dataframe(table, use_container_width=True, hide_index=True)
            counts = core.sensitivity_summary(fields)
            if counts:
                summary = " · ".join("%s: %d" % (core.SENSITIVITY[kind]["label"], count)
                                     for kind, count in counts.items())
                st.warning("В документе значимые значения — %s. За пределы контура такое "
                           "выносить нельзя без обезличивания (152-ФЗ, ст. 3, п. 9)." % summary)
        else:
            st.info("Полей правилами не нашлось. Ниже — текст, который прочитала система.")

        if checks:
            st.markdown("### Сверка кодов по классификаторам")
            st.dataframe([{"Код": item["code"], "Значение": item["value"],
                           "Проверка": item["verdict"],
                           "Как проверено": "арифметика" if item["reliable"] else "формат",
                           "Смысл": item["meaning"]} for item in checks],
                         use_container_width=True, hide_index=True)

        if abbreviations:
            st.markdown("### Сокращения в документе")
            for key in abbreviations:
                st.markdown("- **%s** — %s" % (key, glossary.tooltip(key)))

        with st.expander("Что прочитано с документа (%d знаков, %d цифр)"
                         % (len(full_text), sum(1 for symbol in full_text if symbol.isdigit()))):
            st.code(full_text[:4000] or "текст не распознан")

        act = core.build_act_text(fields, name, masks)
        st.download_button("Скачать черновик акта (TXT)", act,
                           file_name="act.txt", mime="text/plain")

    with right:
        st.markdown("### Оригинал документа")
        image = preview_png(path)
        if image is None:
            st.info("Для этого типа файла картинку не показываем — смотрите текст слева.")
        else:
            if "turn" not in st.session_state:
                st.session_state.turn = 0
            first, second, third = st.columns(3)
            if first.button("⟲ влево"):
                st.session_state.turn = (st.session_state.turn + 270) % 360
            if second.button("⟳ вправо"):
                st.session_state.turn = (st.session_state.turn + 90) % 360
            if third.button("ровно"):
                st.session_state.turn = 0
            st.caption("поворот: %d° · сервис уже развернул снимок «ногами вниз»"
                       % st.session_state.turn)
            st.image(image, use_container_width=True,
                     caption="Оригинал: сверяйте с полями слева")


def tab_laws():
    st.subheader("Вопрос по законам")
    connected = engine_available()
    if not connected:
        st.info("Локальный движок Ollama на этой машине не отвечает. Покажу найденные пункты базы — "
                "ответ большой модели появится, когда движок запущен (на своём компьютере).")
    question = st.text_input("Ваш вопрос", value=QUESTION_EXAMPLES[0])
    st.caption("Примеры: " + " · ".join(QUESTION_EXAMPLES[1:4]))

    if not st.button("Спросить", type="primary"):
        return
    records = core.load_base()
    if not connected:
        matches = core.search_base(question, records) if records else []
        for item in matches:
            st.markdown("- **%s, %s** — %s" % (item["document"], item["clause"],
                                               item["text"][:240]))
        return
    with st.spinner("Ищу в базе и спрашиваю модель…"):
        result = core.answer_by_laws(question)
    if result["refusal"]:
        st.warning("В БАЗЕ НЕТ ОТВЕТА — это честный отказ. Система не стала придумывать. "
                   "Что ответила модель: %s" % result["answer"])
    else:
        st.markdown("**Ответ:** %s" % result["answer"])
        st.markdown("**Источник:** %s" % (result["source"] or "(модель не назвала пункт)"))
    st.markdown("**Проверка кодом:** ссылка на пункт — %s · чисел вне базы — %d"
                % ("да" if result["source_ok"] else "НЕТ", len(result["numbers_outside"])))
    with st.expander("Что найдено в базе"):
        for item in result["matches"]:
            st.markdown("- **%s, %s** — %s" % (item["document"], item["clause"],
                                               item["text"][:240]))


def tab_glossary():
    st.subheader("Библиотека сокращений")
    query = st.text_input("Поиск по сокращению или названию", "")
    entries = glossary.list_all()
    rows = []
    for key, entry in entries:
        haystack = " ".join([key, entry.get("full", ""), entry.get("note", "")]).lower()
        if query and query.lower() not in haystack:
            continue
        rows.append({"Сокращение": key, "Полное название": entry.get("full", ""),
                     "Латиницей": entry.get("latin", "—"),
                     "Читается": entry.get("spoken", "—"),
                     "Свои значения": "; ".join(item.get("meaning", "")
                                                for item in entry.get("variants", [])) or "—",
                     "Источник": entry.get("source", "")})
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.form("add_abbreviation"):
        st.markdown("**Добавить своё значение** (прежние не затираются)")
        key = st.text_input("Сокращение", placeholder="например ОКУД")
        meaning = st.text_input("Что оно значит для вас")
        author = st.text_input("Кто добавляет", value="пользователь")
        if st.form_submit_button("Добавить"):
            st.success(glossary.add_variant(key, meaning, author))


def tab_about():
    st.subheader("О приложении")
    st.markdown(
        "**Нейро-сотрудник** — помощник обслуживающей организации (УК, ТСЖ). Читает документы, "
        "достаёт поля правилами, сверяет сроки и коды с законами и справочниками, собирает проект акта.\n\n"
        "**Как устроено:** модель предлагает — правило решает. Модель читает и формулирует, "
        "а числа, сроки, проверку чисел и сборку акта делает код.\n\n"
        "**Модули:** `app.py` — этот экран · `core.py` — база знаний, поиск, ответ, поля, значимость · "
        "`recognition.py` — текст с фото (Тесеракт) · `codes.py` — QR, штрих-коды, сверка кодов · "
        "`glossary.py` — библиотека сокращений.\n\n"
        "**Чего нет:** годовых и месячных отчётов, сводки «что просрочено», распознавания "
        "рукописного текста, голосового ввода.\n\n"
        "**Где работает:** локально (движок Ollama, модели qwen2.5:3b и bge-m3, Тесеракт). "
        "Отправка документов наружу помечается цветом: ПДн, секрет, оплата, API-ключ, идентификатор."
    )
    st.caption("Данные: %s · записей в базе: %d · сокращений: %d · кодов ОКУД: %d"
               % (os.path.basename(core.BASE_PATH), len(core.load_base()),
                  len(glossary.list_all()), len(codes.okud_codes()[0])))


def main():
    st.title("Нейро-сотрудник")
    st.caption("Документы жителей, законы и учёт — на одном экране. "
               "Локально: движок Ollama и распознавание работают на этом компьютере.")
    document_tab, laws_tab, glossary_tab, about_tab = st.tabs(
        ["Документ", "Вопрос по законам", "Сокращения", "О приложении"])
    with document_tab:
        tab_document()
    with laws_tab:
        tab_laws()
    with glossary_tab:
        tab_glossary()
    with about_tab:
        tab_about()


main()
