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

DEMO_DOCUMENT = """АКТ № 47-ВК
проверки состояния и функционирования вентиляционных каналов

Объект: многоквартирный дом № 12 по ул. Ленина
Дата составления: 20.03.2026
Основание (договор): договор № 9 от 11.01.2026
Заказчик: ООО «Управляющая компания Сервис-Пример»
Исполнитель: ИП Пилюгин А. В., телефон 8 487 231-30-10
Прибор: анемометр, заводской номер 1234, поверка до 14.02.2027
Проверено каналов: 18
Результат: тяга обеспечена во всех 18 каналах
Выявленные дефекты: не выявлены
Срок следующей проверки: август—сентябрь 2026
Подпись исполнителя: имеется
"""

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


def analyse_text(pages, name):
    """Разбор готового текста: вид, поля, коды, карточка, значимость."""
    full_text = "\n".join(page["text"] for page in pages)
    doc_type = core.document_type(full_text)
    fields = core.extract_fields(pages, doc_type)
    if len(fields) < 6:          # догадки — только когда правилами нашлось мало
        fields += core.guess_fields(pages, fields, limit=6)
    fields = core.mark_values(fields)
    card = core.document_card(doc_type, fields, [])
    blank = core.empty_form(full_text, fields)
    checks = codes.check_text(full_text)
    abbreviations = glossary.find_in_text(full_text)
    return {"pages": pages, "text": full_text, "type": doc_type, "fields": fields,
            "card": card, "blank": blank, "checks": checks,
            "abbreviations": abbreviations, "name": name, "codes": []}


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


def document_image(path, scale=1.0, shift_x=0.5, shift_y=0.5):
    """Картинка документа для показа.

    scale  — приближение: 1 = весь лист; 8 = узкая полоса, но в полном разрешении;
    shift_x, shift_y — положение лупы (0…1) по ширине и высоте.

    Для PDF область рендерится заново с большим увеличением — поэтому буквы остаются
    резкими, а не растянутыми. Для фото берётся исходный файл без уменьшения.
    """
    try:
        import cv2
        import numpy as np
        import pymupdf

        доля = 1.0 / max(scale, 1.0)                 # какую часть листа показываем
        левый_край = min(max(shift_x - доля / 2, 0.0), 1.0 - доля)
        верхний_край = min(max(shift_y - доля / 2, 0.0), 1.0 - доля)

        if str(path).lower().endswith(".pdf"):
            document = pymupdf.open(path)
            try:
                страница = document[0]
                рамка = страница.rect
                область = pymupdf.Rect(
                    рамка.x0 + рамка.width * левый_край,
                    рамка.y0 + рамка.height * верхний_край,
                    рамка.x0 + рамка.width * (левый_край + доля),
                    рамка.y0 + рамка.height * (верхний_край + доля))
                # увеличение подбираем так, чтобы картинка была около 1600 точек
                точек = 1600.0
                увеличение = точек / max(1.0, max(область.width, область.height))
                увеличение = min(max(увеличение, 2.0), 12.0)
                поток = страница.get_pixmap(matrix=pymupdf.Matrix(увеличение, увеличение),
                                           clip=область).tobytes("png")
            finally:
                document.close()
        else:
            with open(path, "rb") as файл:
                поток = файл.read()

        картинка = cv2.imdecode(np.frombuffer(поток, dtype=np.uint8), cv2.IMREAD_COLOR)
        if картинка is None:
            return None

        if not str(path).lower().endswith(".pdf"):
            # фото: вырезаем область из оригинала, без растяжения
            высота, ширина = картинка.shape[:2]
            x0 = int(ширина * левый_край)
            y0 = int(высота * верхний_край)
            x1 = int(ширина * (левый_край + доля))
            y1 = int(высота * (верхний_край + доля))
            картинка = картинка[y0:y1, x0:x1]
            длинная = max(картинка.shape[:2])
            if длинная > 1800:
                коэффициент = 1800 / длинная
                картинка = cv2.resize(картинка, (int(картинка.shape[1] * коэффициент),
                                                 int(картинка.shape[0] * коэффициент)))

        угол = recognition.orientation_angle(_png_on_disk(поток))
        if угол in (90, 180, 270):
            повороты = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                        270: cv2.ROTATE_90_COUNTERCLOCKWISE}
            картинка = cv2.rotate(картинка, повороты[угол])
        return cv2.cvtColor(картинка, cv2.COLOR_BGR2RGB)
    except Exception:      # noqa: BLE001
        return None


def zoom_crop(image, scale, shift_x, shift_y):
    """Вырезать область и растянуть её — так работает приближение.

    scale    — во сколько раз приближаем (1 = весь лист);
    shift_x  — сдвиг по ширине 0…1 (0 — левый край, 1 — правый);
    shift_y  — сдвиг по высоте 0…1 (0 — верх, 1 — низ).
    """
    import cv2
    if scale <= 1.01:
        return image
    height, width = image.shape[:2]
    window_w, window_h = max(64, int(width / scale)), max(64, int(height / scale))
    left = int((width - window_w) * min(max(shift_x, 0.0), 1.0))
    top = int((height - window_h) * min(max(shift_y, 0.0), 1.0))
    crop = image[top:top + window_h, left:left + window_w]
    return cv2.resize(crop, (width, height), interpolation=cv2.INTER_CUBIC)


def badge(kind):
    """Метка значимости цветом (рамку рисуем вокруг значения в таблице)."""
    if not kind:
        return ""
    entry = core.SENSITIVITY.get(kind, {})
    return (":%s[**%s**]" % ("red" if kind == "секрет" else "violet", entry.get("label", "")))


# --------------------------------------------------------------------------------- вкладки
def tab_document():
    st.subheader("Документ")

    ocr_ready = recognition.has_tesseract()
    if not ocr_ready:
        st.info(
            "**Фото на этом сервере не читается — так и задумано.** Здесь нет программы "
            "распознавания (Тесеракт): в облаке её не установить. Три рабочих пути:\n\n"
            "1. **Загрузите PDF с текстом** (не скан) — читается сразу.\n"
            "2. **Вставьте текст вручную** — ниже, в поле «Вставить текст документа»: "
            "тогда работают поля, смысловая карточка, значимость и черновик акта.\n"
            "3. **Запустить на своём компьютере** — там работает полное чтение фото "
            "(`streamlit run app.py`)."
        )

    source = st.radio("Откуда берём документ",
                      options=["Файл", "Вставить текст", "Показать пример"],
                      horizontal=True)

    pages, name, needs_ocr, path = [], "", False, None
    if source == "Файл":
        uploaded = st.file_uploader("Загрузите PDF или фото документа (JPG, PNG)",
                                    type=["pdf", "jpg", "jpeg", "png", "tif", "tiff", "webp"])
        if not uploaded:
            st.caption("PDF с текстовым слоем читается в любом случае. Фото — только при "
                       "локальном запуске, где установлен Тесеракт.")
            return
        with st.spinner("Читаю документ…"):
            pages, name, needs_ocr, path = read_document(uploaded)
    elif source == "Вставить текст":
        pasted = st.text_area("Текст документа", height=220,
                              placeholder="Вставьте сюда текст заявления, акта или чека")
        if not pasted.strip():
            st.caption("Пока пусто. Вставьте текст — и приложение разберёт его так же, как файл.")
            return
        pages, name = [{"page": 1, "text": pasted}], "текст, вставленный вручную"
    else:
        st.caption("Это встроенный пример акта проверки вентиляционных каналов — чтобы увидеть, "
                   "как работает разбор, без подготовки файла.")
        pages, name = [{"page": 1, "text": DEMO_DOCUMENT}], "пример: акт проверки вентканалов"

    if not any(page["text"].strip() for page in pages):
        st.error(
            "**Текст не прочитан.** Причин две: в файле нет текстового слоя (это скан или фото) "
            "и на этом сервере нет программы распознавания.\n\n"
            "Что делать: 1) загрузите PDF с текстом; 2) вставьте текст вручную; "
            "3) запустите приложение на своём компьютере — там фото читается."
        )
        image = document_image(path) if path else None
        if image is not None:
            st.image(image, caption="Загруженный снимок: сверьте глазами", use_container_width=True)
        return

    with st.spinner("Разбираю документ…"):
        result = analyse_text(pages, name)
        if path:
            found = codes.find_codes(path)
            extra = codes.parse_codes(found)
            if extra:
                result["fields"] = core.mark_values(result["fields"] + extra)
                result["codes"] = found
                result["card"] = core.document_card(result["type"], result["fields"], found)
        if needs_ocr:
            st.warning("В файле нет текстового слоя — читал распознаванием, качество зависит "
                       "от снимка.")

    left, right = st.columns((3, 2))
    fields = result["fields"]
    card = result["card"]

    with left:
        st.markdown("### Смысл документа")
        st.markdown("**Вид документа:** %s" % result["type"])
        st.markdown("**Куда идёт в учёте:** %s — %s" % (card["destination"], card["action"]))
        st.markdown("**Обязательно должно быть:** %s" % card["required"])
        if card["missing"]:
            st.error("Не хватает: %s" % ", ".join(card["missing"]))
        elif card["required"] != "—":
            st.success("Всё обязательное на месте")
        if result["blank"]["empty"]:
            st.error("Похоже на **пустой бланк**: метки полей есть (%s), а значений нет."
                     % ", ".join(result["blank"]["markers"]))

        st.markdown("### Поля документа")
        masks = st.multiselect("Что заменить маской в акте и реестре:",
                               options=list(core.SENSITIVITY.keys()),
                               format_func=lambda key: core.SENSITIVITY[key]["label"],
                               default=["секрет", "ключ"])
        if fields:
            table = []
            for item in fields:
                hidden = item.get("kind") in masks
                table.append({
                    "Поле": ("[" + item.get("label", "") + "] " if item.get("label") else "") + item["field"],
                    "Значение": (core.mask_value(item["value"], item.get("kind"))
                                 if hidden else item["value"]),
                    "Значимость": item.get("label", "—"),
                    "Где": "стр. %s, строка %s" % (item.get("page"), item.get("line")),
                    "Как найдено": item.get("how", ""),
                })
            st.dataframe(table, use_container_width=True, hide_index=True)
            counts = core.sensitivity_summary(fields)
            if counts:
                summary = " · ".join("%s: %d" % (core.SENSITIVITY[kind]["label"], count)
                                     for kind, count in counts.items())
                st.warning("В документе значимые значения — %s. За пределы контура такое выносить "
                           "нельзя без обезличивания (152-ФЗ, ст. 3, п. 9)." % summary)
        else:
            st.info("Полей правилами не нашлось. Ниже — текст, который прочитала система.")

        if result["checks"]:
            st.markdown("### Сверка кодов по классификаторам")
            st.dataframe([{"Код": item["code"], "Значение": item["value"],
                           "Проверка": item["verdict"],
                           "Как проверено": "арифметика" if item["reliable"] else "формат",
                           "Смысл": item["meaning"]} for item in result["checks"]],
                         use_container_width=True, hide_index=True)

        if result["abbreviations"]:
            st.markdown("### Сокращения в документе")
            for key in result["abbreviations"]:
                st.markdown("- **%s** — %s" % (key, glossary.tooltip(key)))

        with st.expander("Что прочитано с документа (%d знаков, %d цифр)"
                         % (len(result["text"]),
                            sum(1 for symbol in result["text"] if symbol.isdigit()))):
            st.code(result["text"][:4000] or "текст не распознан")

        act = core.build_act_text(fields, name, masks)
        st.download_button("Скачать черновик акта (TXT)", act,
                           file_name="act.txt", mime="text/plain")

    with right:
        st.markdown("### Оригинал документа")
        image = document_image(path) if path else None
        if image is None:
            st.info("Показан текст без картинки: для вставленного текста и примера "
                    "оригинала нет.")
        else:
            if "turn" not in st.session_state:
                st.session_state.turn = 0
            поворот_кнопки = st.columns(3)
            if поворот_кнопки[0].button("⟲ влево"):
                st.session_state.turn = (st.session_state.turn + 270) % 360
            if поворот_кнопки[1].button("⟳ вправо"):
                st.session_state.turn = (st.session_state.turn + 90) % 360
            if поворот_кнопки[2].button("ровно"):
                st.session_state.turn = 0
            st.caption("поворот: %d° · сервис уже развернул снимок «ногами вниз»"
                       % st.session_state.turn)

            # приближение: разглядеть строчку, тени и нажим ручки
            scale = st.slider("Приближение (×)", 1.0, 8.0, 1.0, 0.5,
                              help="1 — весь лист; 8 — самая крупная лупа. "
                                   "Положение лупы задаётся ползунками ниже.")
            shift_x, shift_y = 0.5, 0.5
            if scale > 1.01:
                ползунки = st.columns(2)
                shift_x = ползунки[0].slider("Сдвиг по ширине", 0.0, 1.0, 0.5, 0.05)
                shift_y = ползунки[1].slider("Сдвиг по высоте", 0.0, 1.0, 0.5, 0.05)
                st.caption("лупа %.1f× · видно %.0f%% листа" % (scale, 100 / scale))
            резкая = document_image(path, scale, shift_x, shift_y) if scale > 1.01 else image
            st.image(резкая if резкая is not None else image, use_container_width=True,
                     caption="Оригинал: приближение %.1f× · сверяйте с полями слева" % scale)


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
