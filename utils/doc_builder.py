"""
doc_builder.py
Замена mlreportgen.dom.* → python-docx

Вспомогательные функции для создания .docx бюллетеня
с нужным форматированием (Times New Roman 12pt, выравнивание, отступы).
"""

from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy


def _set_paragraph_spacing(para, space_before: int = 0, space_after: int = 0,
                            line_spacing: float = 1.0):
    """Убирает автоматические отступы абзаца и задаёт межстрочный интервал."""
    pf = para.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after  = Pt(space_after)
    pf.line_spacing = Pt(12 * line_spacing)  # одинарный = 12pt для 12pt шрифта


def add_spacer(doc: Document):
    """Добавляет пустую строку без отступов — аналог clone(spacer) в MATLAB."""
    para = doc.add_paragraph(" ")
    _set_paragraph_spacing(para)
    return para


def add_header(doc: Document, text: str, font_size: int = 12,
               bold: bool = True, align: str = "center") -> None:
    """
    Добавляет заголовочный абзац.

    Parameters
    ----------
    text      : str  — текст абзаца
    font_size : int  — размер шрифта в pt
    bold      : bool — жирное начертание
    align     : str  — 'center', 'left', 'right', 'justify'
    """
    para = doc.add_paragraph()
    _set_paragraph_spacing(para)

    run = para.add_run(text)
    run.font.name      = "Times New Roman"
    run.font.size      = Pt(font_size)
    run.font.bold      = bold

    align_map = {
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "right":   WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    para.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.CENTER)


def add_body_paragraph(doc: Document, text: str) -> None:
    """Добавляет основной текстовый абзац с выравниванием по ширине."""
    para = doc.add_paragraph()
    _set_paragraph_spacing(para)

    run = para.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run.font.bold = False

    para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def create_bulletin_doc(output_path: str,
                        bulletin_type: str,
                        header_title: str,
                        header_date_line: str,
                        days: list[dict]) -> str:
    """
    Создаёт .docx бюллетень.

    Parameters
    ----------
    output_path     : str  — полный путь для сохранения файла
    bulletin_type   : str  — 'morning' или 'evening' (для лога)
    header_title    : str  — верхний заголовок, напр. 'ГИДРОМЕТЕОРОЛОГИЧЕСКИЙ БЮЛЛЕТЕНЬ'
    header_date_line: str  — строка с датой и временем
    days            : list[dict] — каждый элемент содержит:
                        'period_label' : str  — подзаголовок периода
                        'body'         : str  — основной текст

    Returns
    -------
    output_path : str — путь к созданному файлу
    """
    doc = Document()

    # Убираем отступы у стиля Normal
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)

    # Два отступа в начале (как append(doc, spacer) × 2)
    add_spacer(doc)
    add_spacer(doc)

    # Заголовок
    add_header(doc, header_title, font_size=12, bold=True, align="center")
    add_header(doc, header_date_line, font_size=12, bold=True, align="center")

    add_spacer(doc)
    add_spacer(doc)

    # Подзаголовок «ПРОГНОЗ ПОГОДЫ»
    add_header(doc, "ПРОГНОЗ ПОГОДЫ", font_size=11, bold=True, align="center")

    add_spacer(doc)
    add_spacer(doc)

    # Блоки по суткам
    for day in days:
        # Подзаголовок периода (жирный, по центру)
        add_header(doc, day["period_label"], font_size=12, bold=True, align="center")
        add_spacer(doc)

        # Основной текст
        add_body_paragraph(doc, day["body"])
        add_spacer(doc)

    doc.save(output_path)
    return output_path
