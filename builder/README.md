# builder/ — wkład własny firmy (dowody)

Ten folder dokumentuje oprogramowanie wytworzone we własnym zakresie, na potrzeby księgowe /
audytowe („wkład własny").

- `screenshots/` — zrzuty ekranu działających modułów (dowód wizualny). Każdy nowy wygenerowany
  ekran trafia tutaj.
- `report_data.py` — rejestr komponentów (nazwa, opis, pracochłonność w osobodniach).
  **Po każdej skończonej rzeczy dopisujemy do niego kolejną pozycję.**
- `build_report.py` — generuje raport: `raport_wklad_wlasny.pdf` + `.md`
  (zestawienie + szacunkowa wartość na rynek polski). Bez zewnętrznych bibliotek.
- `make_pdf.py` — minimalny generator PDF (czysty Python).

Aktualizacja raportu po dodaniu nowej pozycji:
```bash
cd builder && python build_report.py
```

Wartości są szacunkowe (koszt wytworzenia = osobodni × stawka rynkowa) i poglądowe — nie są
oficjalną wyceną rzeczoznawcy.
