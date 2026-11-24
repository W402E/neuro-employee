# -*- coding: utf-8 -*-
r"""RECOGNITION — текст с картинки или скана (English identifiers, 23.11.2026).

Русский текст остаётся только в сообщениях для человека; все имена — английские
(требование куратора). Работает на Тесеракте, локально, без интернета.

Почему свои повороты: телефон пишет снимок «как держали», и Тесеракт на перевёрнутой картинке
даёт мусор. Поэтому пробуем 0/90/180/270 и оставляем тот поворот, где больше настоящих слов
и цифр (замер 04.11.2026: 4 поворота против одного — разница в разы).
"""
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: BLE001
    pass

TESSERACT_CANDIDATES = (r"C:\Program Files\Tesseract-OCR\tesseract.exe", "tesseract")
LANGUAGES = "rus+eng"
TARGET_PIXELS = 2000          # длинная сторона картинки для распознавания
ROTATIONS = (0, 90, 180, 270)
MIN_TEXT = 20                 # меньше знаков — считаем, что страницу не прочитали


def tesseract_path():
    """Где лежит Тесеракт: сначала обычный путь установки, потом PATH."""
    for candidate in TESSERACT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def has_tesseract():
    return tesseract_path() is not None


def quality(text):
    """Чем больше настоящих русских слов и цифр — тем правдоподобнее поворот."""
    words = len(re.findall(r"\b[а-яё]{3,}\b", (text or "").lower()))
    digits = sum(1 for symbol in (text or "") if symbol.isdigit())
    return words * 2 + digits


def _ocr_once(path, page, pixels, mode, angle):
    """Одна страница (или картинка) в одном повороте. Пустая строка — если не вышло."""
    import pymupdf

    binary = tesseract_path()
    if not binary:
        return ""
    work_dir = tempfile.mkdtemp(prefix="ocr_")
    image_path = os.path.join(work_dir, "page.png")
    base_path = os.path.join(work_dir, "text")
    try:
        document = pymupdf.open(path)
        try:
            sheet = document[page - 1]
            longest = max(sheet.rect.width, sheet.rect.height) or 1
            factor = min(3.0, pixels / longest)
            matrix = pymupdf.Matrix(factor, factor)
            if angle:
                matrix = matrix.prerotate(angle)
            sheet.get_pixmap(matrix=matrix).save(image_path)
        finally:
            document.close()
        subprocess.run([binary, image_path, base_path, "-l", LANGUAGES, "--psm", mode],
                       check=False, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result_path = base_path + ".txt"
        if not os.path.exists(result_path):
            return ""
        with open(result_path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except Exception:      # noqa: BLE001 — распознавание не должно ронять разбор
        return ""
    finally:
        for name in os.listdir(work_dir):
            try:
                os.remove(os.path.join(work_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(work_dir)
        except OSError:
            pass


def read_page(path, page=1, pixels=TARGET_PIXELS, mode="3"):
    """Текст одной страницы без поворотов."""
    return _ocr_once(path, page, pixels, mode, 0)


def read_page_best(path, page=1, pixels=TARGET_PIXELS, mode="3"):
    """Текст страницы с выбором лучшего поворота. Возвращает (text, angle)."""
    best_text, best_angle, best_score = "", 0, -1
    for angle in ROTATIONS:
        text = _ocr_once(path, page, pixels, mode, angle)
        score = quality(text)
        if score > best_score:
            best_text, best_angle, best_score = text, angle, score
    return best_text, best_angle


def orientation_angle(png_path):
    """Насколько текст повёрнут: 0, 90, 180 или 270 (проверка ориентации Тесеракта)."""
    binary = tesseract_path()
    if not binary:
        return 0
    try:
        result = subprocess.run([binary, png_path, "-", "--psm", "0"],
                                capture_output=True, text=True, timeout=90)
        match = re.search(r"Rotate:\s*(\d+)", result.stdout or "")
        return int(match.group(1)) if match else 0
    except Exception:      # noqa: BLE001
        return 0


def page_count(path):
    """Сколько страниц в PDF (0 — если файл не PDF)."""
    try:
        import pymupdf
        document = pymupdf.open(path)
        try:
            return len(document)
        finally:
            document.close()
    except Exception:      # noqa: BLE001
        return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text, angle = read_page_best(sys.argv[1], 1)
        print("поворот: %s · знаков: %d · цифр: %d"
              % (angle, len(text), sum(1 for symbol in text if symbol.isdigit())))
        print(text[:400])
    else:
        print("Тесеракт:", tesseract_path() or "НЕ НАЙДЕН")
        print("Запуск: python recognition.py \"путь\\к\\скану.pdf\"")
