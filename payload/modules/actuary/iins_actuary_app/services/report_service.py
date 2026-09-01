"""Аналитические отчёты кабинета актуария.

Отчёт собирается в три шага, и границы между ними в документе видны явно:

  1. Расчёт     — числа берутся из базы кабинета и из метрик обученной модели.
                  Ни одно значение не придумывается и не округляется задним числом.
  2. Интерпретация — выбранная языковая модель (Qwen RAG или GigaChat) получает
                  только вычисленные числа и объясняет их словами. Раздел в PDF
                  подписан именем модели и режимом, которым он получен.
  3. Документ   — PDF со сводкой, таблицами, интерпретацией и оговоркой о том,
                  какая часть посчитана, а какая написана моделью.

Разделение сделано намеренно: прогноз и его словесное объяснение имеют разное
происхождение, и в отчёте это должно оставаться видимым.
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from iins_actuary_app.config import ROOT, get_settings
from iins_actuary_app.models import CgrDefinition, PremiumCase, TerritoryDefinition

# Каталог считается от этого файла, а не от имени пакета: у кабинета в
# репозитории пакет называется app, а в комплекте — iins_actuary_iins_actuary_app.
FONT_DIR = Path(__file__).resolve().parent.parent / "assets"
DISCLAIMER = (
    "Раздел «Расчёт» получен из данных кабинета. Раздел «Интерпретация» написан "
    "языковой моделью по этим числам и не является актуарным заключением: перед "
    "использованием в тарификации выводы подлежат проверке ответственным актуарием."
)


# --------------------------------------------------------------- структура
@dataclass
class Table:
    columns: List[str]
    rows: List[List[str]]
    note: str = ""


@dataclass
class Section:
    heading: str
    paragraphs: List[str] = field(default_factory=list)
    table: Optional[Table] = None


@dataclass
class Report:
    kind: str
    title: str
    subtitle: str
    sections: List[Section]
    facts: Dict[str, Any]
    interpretation: str = ""
    lm_mode: str = ""
    lm_model: str = ""
    author: str = ""
    created_at: str = ""


def reports_dir() -> Path:
    base = os.getenv("DOCS_STORAGE_DIR") or str(ROOT / "data")
    path = Path(base) / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------ утилиты
def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return f"{value:,}".replace(",", " ")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "—"
        text = f"{value:,.{digits}f}".replace(",", " ")
        return text.replace(".", ",")
    return str(value)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(sorted_values[int(pos)])
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low))


def _moments(values: Sequence[float]) -> Dict[str, Any]:
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    n = len(clean)
    if n < 2:
        return {"n": n}
    mean = statistics.fmean(clean)
    sd = statistics.pstdev(clean)
    ordered = sorted(clean)
    skew = kurt = float("nan")
    if sd > 0:
        skew = sum(((v - mean) / sd) ** 3 for v in clean) / n
        kurt = sum(((v - mean) / sd) ** 4 for v in clean) / n - 3.0
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "cv": (sd / mean) if mean else float("nan"),
        "min": ordered[0],
        "q05": _quantile(ordered, 0.05),
        "q25": _quantile(ordered, 0.25),
        "median": _quantile(ordered, 0.50),
        "q75": _quantile(ordered, 0.75),
        "q95": _quantile(ordered, 0.95),
        "max": ordered[-1],
        "skewness": skew,
        "excess_kurtosis": kurt,
    }


def _normality(values: Sequence[float]) -> Dict[str, Any]:
    """Проверка нормальности: Шапиро — Уилка и Д'Агостино, если доступна scipy."""
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    out: Dict[str, Any] = {"n": len(clean)}
    if len(clean) < 8:
        out["note"] = "наблюдений слишком мало для проверки"
        return out
    try:
        from scipy import stats  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        out["note"] = "scipy недоступна — проверка не выполнялась"
        return out
    sample = clean[:5000]
    try:
        w, p_w = stats.shapiro(sample)
        out["shapiro_w"] = float(w)
        out["shapiro_p"] = float(p_w)
    except Exception:  # noqa: BLE001
        pass
    try:
        k2, p_k = stats.normaltest(clean)
        out["dagostino_k2"] = float(k2)
        out["dagostino_p"] = float(p_k)
    except Exception:  # noqa: BLE001
        pass
    ps = [out[k] for k in ("shapiro_p", "dagostino_p") if k in out]
    if ps:
        out["normal_at_005"] = all(p >= 0.05 for p in ps)
    return out


def _load_metrics() -> Dict[str, Any]:
    path = get_settings().model_dir / "metrics.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ------------------------------------------------------------------- отчёты
def _report_distribution(db: Session) -> Report:
    rows = db.query(PremiumCase.selected_premium, PremiumCase.indicated_premium).all()
    selected = [r[0] for r in rows if r[0]]
    indicated = [r[1] for r in rows if r[1]]
    ms, mi = _moments(selected), _moments(indicated)
    norm = _normality(selected)

    stat_table = Table(
        columns=["Показатель", "Отобранная премия", "Индикативная премия"],
        rows=[
            ["Наблюдений", _fmt(ms.get("n")), _fmt(mi.get("n"))],
            ["Среднее", _fmt(ms.get("mean")), _fmt(mi.get("mean"))],
            ["Стандартное отклонение", _fmt(ms.get("sd")), _fmt(mi.get("sd"))],
            ["Коэффициент вариации", _fmt(ms.get("cv"), 3), _fmt(mi.get("cv"), 3)],
            ["Минимум", _fmt(ms.get("min")), _fmt(mi.get("min"))],
            ["5-й процентиль", _fmt(ms.get("q05")), _fmt(mi.get("q05"))],
            ["Первый квартиль", _fmt(ms.get("q25")), _fmt(mi.get("q25"))],
            ["Медиана", _fmt(ms.get("median")), _fmt(mi.get("median"))],
            ["Третий квартиль", _fmt(ms.get("q75")), _fmt(mi.get("q75"))],
            ["95-й процентиль", _fmt(ms.get("q95")), _fmt(mi.get("q95"))],
            ["Максимум", _fmt(ms.get("max")), _fmt(mi.get("max"))],
            ["Асимметрия", _fmt(ms.get("skewness"), 3), _fmt(mi.get("skewness"), 3)],
            ["Эксцесс", _fmt(ms.get("excess_kurtosis"), 3), _fmt(mi.get("excess_kurtosis"), 3)],
        ],
        note="Квантили вычислены линейной интерполяцией по упорядоченной выборке.",
    )

    norm_rows = [["Наблюдений в проверке", _fmt(norm.get("n"))]]
    if "shapiro_w" in norm:
        norm_rows.append(["Шапиро — Уилка, W", _fmt(norm["shapiro_w"], 4)])
        norm_rows.append(["Шапиро — Уилка, p", _fmt(norm["shapiro_p"], 4)])
    if "dagostino_k2" in norm:
        norm_rows.append(["Д'Агостино — Пирсона, K²", _fmt(norm["dagostino_k2"], 3)])
        norm_rows.append(["Д'Агостино — Пирсона, p", _fmt(norm["dagostino_p"], 4)])
    if "normal_at_005" in norm:
        norm_rows.append([
            "Гипотеза нормальности при 0,05",
            "не отвергается" if norm["normal_at_005"] else "отвергается",
        ])
    norm_table = Table(
        columns=["Критерий", "Значение"],
        rows=norm_rows,
        note=norm.get("note", "Проверка выполнена по отобранной премии."),
    )

    sections = [
        Section(
            "Расчёт: моменты и квантили",
            ["Выборка охватывает все строки премий, загруженные в кабинет. "
             "Показатели считаются по фактическим значениям без отбрасывания выбросов."],
            stat_table,
        ),
        Section(
            "Расчёт: проверка нормальности",
            ["Нормальность проверяется потому, что от неё зависит правомерность "
             "нормальных доверительных интервалов и правил «трёх сигм» при "
             "тарификации. Асимметрия и эксцесс приведены выше как ориентир формы."],
            norm_table,
        ),
    ]
    return Report(
        kind="distribution",
        title="Распределение премии: моменты, квантили и проверка нормальности",
        subtitle="Кабинет актуария, тарифный портфель",
        sections=sections,
        facts={"selected": ms, "indicated": mi, "normality": norm},
    )


def _report_portfolio(db: Session) -> Report:
    total = db.query(PremiumCase).count()
    avg_sel = db.query(func.avg(PremiumCase.selected_premium)).scalar() or 0.0
    avg_ind = db.query(func.avg(PremiumCase.indicated_premium)).scalar() or 0.0
    sum_sel = db.query(func.sum(PremiumCase.selected_premium)).scalar() or 0.0
    sum_ind = db.query(func.sum(PremiumCase.indicated_premium)).scalar() or 0.0
    ratio = (sum_sel / sum_ind) if sum_ind else float("nan")

    by_terr = (
        db.query(
            PremiumCase.territory,
            func.count(PremiumCase.id),
            func.avg(PremiumCase.selected_premium),
            func.avg(PremiumCase.indicated_premium),
        )
        .group_by(PremiumCase.territory)
        .order_by(func.count(PremiumCase.id).desc())
        .limit(12)
        .all()
    )
    terr_rows = [
        [t or "—", _fmt(int(n)), _fmt(float(s or 0.0)), _fmt(float(i or 0.0)),
         _fmt((float(s or 0.0) / float(i)) if i else float("nan"), 3)]
        for t, n, s, i in by_terr
    ]

    by_cgr = (
        db.query(
            PremiumCase.cgr,
            func.count(PremiumCase.id),
            func.avg(PremiumCase.selected_premium),
            func.avg(PremiumCase.cgr_factor),
        )
        .group_by(PremiumCase.cgr)
        .order_by(func.count(PremiumCase.id).desc())
        .limit(12)
        .all()
    )
    cgr_rows = [
        [c or "—", _fmt(int(n)), _fmt(float(s or 0.0)), _fmt(float(f or 0.0), 3)]
        for c, n, s, f in by_cgr
    ]

    sections = [
        Section(
            "Расчёт: портфель целиком",
            ["Соотношение отобранной и индикативной премии показывает, насколько "
             "фактический тариф отклоняется от расчётного ориентира по портфелю."],
            Table(
                ["Показатель", "Значение"],
                [
                    ["Строк премий", _fmt(total)],
                    ["Средняя отобранная премия", _fmt(float(avg_sel))],
                    ["Средняя индикативная премия", _fmt(float(avg_ind))],
                    ["Сумма отобранной премии", _fmt(float(sum_sel))],
                    ["Сумма индикативной премии", _fmt(float(sum_ind))],
                    ["Отношение отобранной к индикативной", _fmt(ratio, 4)],
                ],
            ),
        ),
        Section(
            "Расчёт: срез по территориям",
            ["Двенадцать территорий с наибольшим числом наблюдений."],
            Table(
                ["Территория", "Строк", "Средняя отобранная", "Средняя индикативная", "Отношение"],
                terr_rows,
            ),
        ),
        Section(
            "Расчёт: срез по группам CGR",
            ["Двенадцать групп с наибольшим числом наблюдений."],
            Table(["CGR", "Строк", "Средняя отобранная", "Средний коэффициент"], cgr_rows),
        ),
    ]
    return Report(
        kind="portfolio",
        title="Портфель премий: структура и отклонение от ориентира",
        subtitle="Кабинет актуария, срез по территориям и группам CGR",
        sections=sections,
        facts={
            "rows": total,
            "avg_selected": float(avg_sel),
            "avg_indicated": float(avg_ind),
            "sum_selected": float(sum_sel),
            "sum_indicated": float(sum_ind),
            "selected_to_indicated": ratio,
            "territories": [
                {"territory": t, "rows": int(n), "avg_selected": float(s or 0.0),
                 "avg_indicated": float(i or 0.0)}
                for t, n, s, i in by_terr
            ],
            "cgr": [
                {"cgr": c, "rows": int(n), "avg_selected": float(s or 0.0),
                 "avg_factor": float(f or 0.0)}
                for c, n, s, f in by_cgr
            ],
        },
    )


def _report_model(db: Session) -> Report:
    metrics = _load_metrics()
    models = metrics.get("models") or []
    if not models and metrics.get("primary"):
        models = [metrics["primary"]]

    rows = []
    for item in models:
        if not isinstance(item, dict):
            continue
        rows.append([
            str(item.get("estimator") or item.get("name") or "—"),
            _fmt(item.get("mae")),
            _fmt(item.get("rmse")),
            _fmt(item.get("r2"), 4),
            _fmt(item.get("n_rows")),
        ])

    model_path = get_settings().model_dir / "selected_premium.joblib"
    sections = [
        Section(
            "Расчёт: качество тарифной модели",
            ["Значения взяты из отчёта обучения metrics.json — того самого прогона, "
             "которым получен работающий артефакт модели. Метрика, не попавшая в "
             "отчёт обучения, восстановлению задним числом не подлежит."],
            Table(
                ["Класс модели", "MAE", "RMSE", "R²", "Наблюдений"],
                rows or [["нет данных обучения", "—", "—", "—", "—"]],
            ),
        ),
        Section(
            "Расчёт: состояние артефакта",
            [],
            Table(
                ["Показатель", "Значение"],
                [
                    ["Файл модели", "на месте" if model_path.is_file() else "отсутствует"],
                    ["Путь", str(model_path)],
                    ["Классов моделей в отчёте", _fmt(len(rows))],
                ],
            ),
        ),
    ]
    return Report(
        kind="model",
        title="Качество тарифной модели",
        subtitle="Кабинет актуария, отчёт обучения",
        sections=sections,
        facts={"models": models, "artifact_present": model_path.is_file()},
    )


def _report_factors(db: Session) -> Report:
    n_terr_defs = db.query(TerritoryDefinition).count()
    n_cgr_defs = db.query(CgrDefinition).count()
    cgr_defs = db.query(CgrDefinition).order_by(CgrDefinition.cgr).limit(15).all()
    rows = [
        [d.cgr or "—", _fmt(d.aa, 3), _fmt(d.bb, 3), _fmt(d.cc, 3),
         _fmt(d.va, 3), _fmt(d.dd, 3), _fmt(d.hh, 3), _fmt(d.ss, 3)]
        for d in cgr_defs
    ]
    sections = [
        Section(
            "Расчёт: справочники факторов",
            [],
            Table(
                ["Показатель", "Значение"],
                [
                    ["Определений территорий", _fmt(n_terr_defs)],
                    ["Определений CGR", _fmt(n_cgr_defs)],
                ],
            ),
        ),
        Section(
            "Расчёт: коэффициенты групп CGR",
            ["Первые пятнадцать групп в алфавитном порядке."],
            Table(["CGR", "AA", "BB", "CC", "VA", "DD", "HH", "SS"], rows),
        ),
    ]
    return Report(
        kind="factors",
        title="Тарифные факторы: территории и группы CGR",
        subtitle="Кабинет актуария, справочники",
        sections=sections,
        facts={"territory_definitions": n_terr_defs, "cgr_definitions": n_cgr_defs},
    )


KINDS: Dict[str, Dict[str, Any]] = {
    "distribution": {
        "title": "Распределение премии и проверка нормальности",
        "description": "Моменты, квантили, асимметрия, эксцесс, критерии Шапиро — Уилка "
                       "и Д'Агостино — Пирсона по отобранной премии.",
        "builder": _report_distribution,
    },
    "portfolio": {
        "title": "Портфель премий",
        "description": "Структура портфеля, отношение отобранной премии к индикативной, "
                       "срезы по территориям и группам CGR.",
        "builder": _report_portfolio,
    },
    "model": {
        "title": "Качество тарифной модели",
        "description": "MAE, RMSE и R² по классам моделей из отчёта обучения, "
                       "состояние артефакта модели.",
        "builder": _report_model,
    },
    "factors": {
        "title": "Тарифные факторы",
        "description": "Справочники территорий и групп CGR с коэффициентами.",
        "builder": _report_factors,
    },
}


def available_kinds() -> List[Dict[str, str]]:
    return [
        {"id": key, "title": item["title"], "description": item["description"]}
        for key, item in KINDS.items()
    ]


# ---------------------------------------------------------- интерпретация
_SYSTEM = (
    "Ты — помощник актуария. Тебе дают уже вычисленные показатели тарифного "
    "портфеля. Объясни их деловым языком: что означает каждая величина, что в "
    "ней настораживает и какое действие она подсказывает. "
    "Опирайся ТОЛЬКО на переданные числа. Не добавляй новых величин, не "
    "пересчитывай, не называй источники и имена файлов. Если чисел для вывода "
    "недостаточно, так и скажи. Не давай инвестиционных и юридических "
    "рекомендаций. 4–7 абзацев, без списков, на русском языке."
)


def interpret(report: Report, mode: str = "auto") -> None:
    """Заполняет report.interpretation выбранной языковой моделью."""
    from iins_actuary_app.services.llm_provider import (
        backend_ready,
        generate_reply,
        model_name,
        not_ready_message,
        resolve_backend,
    )

    backend = resolve_backend(mode)
    facts = json.dumps(report.facts, ensure_ascii=False, indent=1, default=str)
    if len(facts) > 12000:
        facts = facts[:12000] + "\n… (показатели усечены)"
    prompt = (
        f"Отчёт: {report.title}\n\n"
        f"Вычисленные показатели в формате JSON:\n{facts}\n\n"
        "Объясни эти показатели актуарию."
    )

    if backend == "extractive":
        report.lm_mode = "extractive"
        report.lm_model = "без языковой модели"
        report.interpretation = (
            "Интерпретация языковой моделью не запрашивалась: выбран режим ответа по "
            "базе знаний. Разделы «Расчёт» выше содержат все вычисленные показатели; "
            "чтобы получить их словесный разбор, выберите режим «Qwen RAG» или "
            "«GigaChat» и постройте отчёт заново."
        )
        return

    if not backend_ready(backend):
        raise RuntimeError(not_ready_message(backend))

    report.lm_mode = backend
    report.lm_model = model_name(backend)
    report.interpretation = generate_reply(
        backend, prompt, max_new_tokens=900, temperature=0.25, system_prompt=_SYSTEM
    ).strip()


# -------------------------------------------------------------------- PDF
_FONT_READY = False


def _require_reportlab() -> None:
    try:
        import reportlab  # noqa: F401, PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Для сборки PDF нужна библиотека reportlab. Запустите ./I-ins.command — "
            "она установится вместе с остальными зависимостями."
        ) from exc


def _register_fonts() -> tuple[str, str]:
    """Регистрирует шрифт с кириллицей. Возвращает (обычный, полужирный)."""
    global _FONT_READY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _FONT_READY:
        return "IIns", "IIns-Bold"
    regular = FONT_DIR / "DejaVuSans.ttf"
    bold = FONT_DIR / "DejaVuSans-Bold.ttf"
    if not regular.is_file():
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("IIns", str(regular)))
    pdfmetrics.registerFont(TTFont("IIns-Bold", str(bold if bold.is_file() else regular)))
    _FONT_READY = True
    return "IIns", "IIns-Bold"


def render_pdf(report: Report, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table as PdfTable,
        TableStyle,
    )

    font, font_bold = _register_fonts()
    base = getSampleStyleSheet()
    st_title = ParagraphStyle("t", parent=base["Title"], fontName=font_bold, fontSize=17, leading=21)
    st_sub = ParagraphStyle("s", parent=base["Normal"], fontName=font, fontSize=10.5,
                            leading=14, textColor=colors.HexColor("#4a4a4a"))
    st_h = ParagraphStyle("h", parent=base["Heading2"], fontName=font_bold, fontSize=12.5,
                          leading=16, spaceBefore=10, spaceAfter=5)
    st_p = ParagraphStyle("p", parent=base["Normal"], fontName=font, fontSize=10,
                          leading=14.5, alignment=TA_JUSTIFY, spaceAfter=6)
    st_note = ParagraphStyle("n", parent=st_p, fontSize=8.6, leading=12,
                             textColor=colors.HexColor("#5a5a5a"))

    def escape(text: str) -> str:
        return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    story: List[Any] = [
        Paragraph(escape(report.title), st_title),
        Paragraph(escape(report.subtitle), st_sub),
        Spacer(1, 5 * mm),
    ]

    meta_rows = [
        ["Отчёт сформирован", report.created_at],
        ["Пользователь", report.author or "—"],
        ["Источник чисел", "база кабинета актуария и отчёт обучения модели"],
        ["Режим интерпретации", report.lm_mode or "—"],
        ["Языковая модель", report.lm_model or "—"],
    ]
    meta = PdfTable([[Paragraph(escape(a), st_note), Paragraph(escape(b), st_note)]
                     for a, b in meta_rows], colWidths=[52 * mm, 108 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f8")),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2da")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dde3e9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [meta, Spacer(1, 6 * mm)]

    for section in report.sections:
        block: List[Any] = [Paragraph(escape(section.heading), st_h)]
        for text in section.paragraphs:
            block.append(Paragraph(escape(text), st_p))
        if section.table and section.table.rows:
            head = [Paragraph(f"<b>{escape(c)}</b>", st_note) for c in section.table.columns]
            body = [[Paragraph(escape(c), st_note) for c in row] for row in section.table.rows]
            ncols = len(section.table.columns)
            first = 58 * mm if ncols <= 3 else 40 * mm
            rest = (160 * mm - first) / max(1, ncols - 1)
            widths = [first] + [rest] * (ncols - 1)
            pdf_table = PdfTable([head] + body, colWidths=widths, repeatRows=1)
            pdf_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf2")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b9c4ce")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5dce3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]))
            block += [Spacer(1, 2 * mm), pdf_table]
            if section.table.note:
                block += [Spacer(1, 1.5 * mm), Paragraph(escape(section.table.note), st_note)]
        story.append(KeepTogether(block) if len(block) <= 3 else block[0])
        if len(block) > 3:
            story += block[1:]
        story.append(Spacer(1, 4 * mm))

    story.append(PageBreak())
    label = f"Интерпретация: {report.lm_model}" if report.lm_model else "Интерпретация"
    story.append(Paragraph(escape(label), st_h))
    story.append(Paragraph(
        escape("Ниже — текст, написанный языковой моделью по вычисленным выше числам. "
               "Модель не имела доступа ни к каким другим данным."), st_note))
    story.append(Spacer(1, 3 * mm))
    for para in [p for p in re.split(r"\n\s*\n", report.interpretation or "") if p.strip()]:
        story.append(Paragraph(escape(para.strip()), st_p))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(escape(DISCLAIMER), st_note))

    def footer(canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor("#7b8794"))
        canvas.drawString(20 * mm, 12 * mm, "I-ins · кабинет актуария")
        canvas.drawRightString(190 * mm, 12 * mm, f"с. {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
        title=report.title, author="I-ins", subject="Аналитический отчёт кабинета актуария",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


# ------------------------------------------------------------------ сборка
def build(kind: str, db: Session, *, mode: str = "auto", author: str = "") -> Dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид отчёта: {kind}")
    _require_reportlab()
    builder: Callable[[Session], Report] = KINDS[kind]["builder"]
    report = builder(db)
    report.author = author
    report.created_at = time.strftime("%d.%m.%Y %H:%M")
    interpret(report, mode)

    rid = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    path = reports_dir() / f"{rid}.pdf"
    render_pdf(report, path)
    return {
        "report_id": rid,
        "kind": kind,
        "title": report.title,
        "created_at": report.created_at,
        "lm_mode": report.lm_mode,
        "lm_model": report.lm_model,
        "interpretation": report.interpretation,
        "sections": [
            {
                "heading": s.heading,
                "paragraphs": s.paragraphs,
                "table": None if not s.table else {
                    "columns": s.table.columns, "rows": s.table.rows, "note": s.table.note,
                },
            }
            for s in report.sections
        ],
        "pdf_bytes": path.stat().st_size,
        "pdf_url": f"/api/report/{rid}.pdf",
    }


def report_path(report_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{4,80}", report_id):
        raise ValueError("Некорректный идентификатор отчёта")
    path = (reports_dir() / f"{report_id}.pdf").resolve()
    if path.parent != reports_dir().resolve() or not path.is_file():
        raise FileNotFoundError("Отчёт не найден")
    return path


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    items = sorted(reports_dir().glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in items[:limit]:
        rid = path.stem
        out.append({
            "report_id": rid,
            "kind": rid.split("-", 1)[0],
            "created_at": time.strftime("%d.%m.%Y %H:%M", time.localtime(path.stat().st_mtime)),
            "bytes": path.stat().st_size,
            "pdf_url": f"/api/report/{rid}.pdf",
        })
    return out
