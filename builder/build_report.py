"""Generate the own-contribution report (markdown + PDF) from report_data.py."""

from __future__ import annotations

import datetime
from pathlib import Path

from make_pdf import build_pdf
from report_data import DAY_RATE_PLN, DELIVERABLES

HERE = Path(__file__).resolve().parent


def grouped() -> dict[str, list[tuple[str, str, int]]]:
    out: dict[str, list[tuple[str, str, int]]] = {}
    for group, item, desc, days in DELIVERABLES:
        out.setdefault(group, []).append((item, desc, days))
    return out


def build() -> tuple[Path, Path]:
    today = datetime.date.today().isoformat()
    total_days = sum(d for *_, d in DELIVERABLES)
    total_value = total_days * DAY_RATE_PLN

    blocks: list[tuple[str, str]] = [
        ("h1", "Raport wkładu własnego — oprogramowanie"),
        ("small", f"Data: {today}"),
        ("p", "Dokument zestawia komponenty oprogramowania wytworzone we własnym zakresie "
              "(wkład własny firmy) wraz z szacunkową wartością rynkową na rynku polskim. "
              "Wartość oszacowano jako koszt wytworzenia: pracochłonność (osobodni) pomnożona "
              "przez stawkę rynkową."),
        ("p", f"Przyjęta stawka: {DAY_RATE_PLN} PLN/osobodzień (netto B2B, ~150 PLN/h x 8h — "
              "typowa stawka mid/senior na rynku polskim). Wartości są szacunkowe i poglądowe, "
              "nie stanowią oficjalnej wyceny rzeczoznawcy."),
    ]
    md = [f"# Raport wkładu własnego — oprogramowanie", f"_Data: {today}_", ""]

    for group, items in grouped().items():
        blocks.append(("h2", group))
        md.append(f"## {group}")
        for item, desc, days in items:
            value = days * DAY_RATE_PLN
            line = f"{item} — {desc}  [{days} os-dni ~ {value:,} PLN]".replace(",", " ")
            blocks.append(("p", f"- {line}"))
            md.append(f"- {line}")
        md.append("")

    blocks.append(("h2", "Podsumowanie"))
    blocks.append(("p", f"Łączna pracochłonność: {total_days} osobodni."))
    blocks.append(("p", f"Szacunkowa wartość (koszt wytworzenia): "
                        f"{total_value:,} PLN netto.".replace(",", " ")))
    blocks.append(("small", "Dowody wizualne (zrzuty ekranu działających modułów) znajdują się "
                            "w folderze builder/screenshots/."))
    md += ["## Podsumowanie",
           f"- Łączna pracochłonność: **{total_days} osobodni**",
           f"- Szacunkowa wartość: **{total_value:,} PLN netto**".replace(",", " "), ""]

    pdf_path = build_pdf(blocks, HERE / "raport_wklad_wlasny.pdf")
    md_path = HERE / "raport_wklad_wlasny.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    return pdf_path, md_path


if __name__ == "__main__":
    pdf, md = build()
    print("PDF:", pdf)
    print("MD :", md)
