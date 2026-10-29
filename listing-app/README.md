# snap2list

Zrób zdjęcie przedmiotu → gotowy opis, kategoria, stan i **cena na rynek polski** → jeden klik
**Wystaw na OLX / Allegro**. Osobny projekt, klient lokalnego modelu wizyjnego (devagent/Ollama).

## Jak działa
1. Robisz zdjęcie w aplikacji webowej (mobilnej, „dodaj do ekranu").
2. `POST /api/describe` wysyła zdjęcie do modelu wizyjnego (OpenAI-compatible) i zwraca gotowe
   ogłoszenie w JSON (tytuł, opis, kategoria, stan, cena + widełki, tagi, atrybuty).
3. Edytujesz jak chcesz i klikasz **Wystaw**:
   - z tokenem API portalu → wystawia przez API (Allegro `/sale/product-offers`, OLX partner),
   - bez tokenu → kopiuje gotowy opis i otwiera formularz portalu do wklejenia (tryb manualny).

## Uruchomienie
```bash
cp .env.example .env            # ustaw LLM_BASE_URL (np. http://<serwer>:8080/v1) i VISION_MODEL
uv venv && uv pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload
# otwórz http://localhost:8000 na telefonie w tej samej sieci
pytest -q && ruff check .
```

## Integracja z portalami
- **Allegro**: REST API z OAuth2 (konto Allegro + rejestracja aplikacji w Allegro Developer).
  Wklej `ALLEGRO_TOKEN` do `.env`. Pełna oferta wymaga kategorii i parametrów — payload w
  `app/publish.py` to minimalny start.
- **OLX**: API partnerskie wymaga konta biznesowego i zgody OLX. `OLX_TOKEN` w `.env`.
- Bez tokenów aplikacja i tak jest użyteczna: generuje opis i otwiera formularz do wklejenia.

## Status
MVP: zdjęcie → opis+cena → wystaw (API lub manualnie). Testy zielone, bez realnych kont portali.
