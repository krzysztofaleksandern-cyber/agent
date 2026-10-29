# Raport wkładu własnego — oprogramowanie
_Data: 2026-10-29_

## Platforma devagent — rdzeń
- Szkielet + konfiguracja + logowanie — FastAPI  ustawienia z .env  bezpieczne logowanie (maskowanie sekretów)  /health  Docker  [3 os-dni ~ 3 600 PLN]
- Warstwa modeli (Ollama/vLLM) — Klient OpenAI-compatible  rejestr modeli z fallbackiem  licznik zużycia  zarządzanie modelami  [4 os-dni ~ 4 800 PLN]
- Publiczne API + klucze — /v1/chat/completions (streaming)  klucze aplikacji (hash w SQLite)  CLI  panel admina  [3 os-dni ~ 3 600 PLN]
- Profile agentów — Definicje agentów w YAML (prompt  model  narzędzia)  walidacja  edycja przez API  [2 os-dni ~ 2 400 PLN]
- Kolejka zadań i trwałość — SQLite  worker asyncio  ponawianie  anulowanie  webhooki podpisane HMAC  [3 os-dni ~ 3 600 PLN]
- Sandbox i narzędzia — Jednorazowy kontener Docker (bez sieci  limity)  narzędzia pliki/shell/git/http  [4 os-dni ~ 4 800 PLN]
- Pętla agenta i orkiestracja — Tool-calling  limit kroków  delegacja między agentami  protokół tekstowy  [4 os-dni ~ 4 800 PLN]
- Bramka zatwierdzeń — Klasyfikacja ryzyka  potwierdzenia TAK/NIE  timeout = odmowa  [2 os-dni ~ 2 400 PLN]
- Pamięć i uczenie z doświadczenia — Historia  oceny  lekcje  embeddingi  RAG  autorefleksja  [4 os-dni ~ 4 800 PLN]
- Uczenie (fine-tuning) — Eksport danych  trening LoRA (Unsloth)  wersjonowanie modeli  ewaluacja  rollback  [4 os-dni ~ 4 800 PLN]
- Wdrożenie — docker-compose VPS+GPU  Caddy HTTPS  systemd  kopie zapasowe  tunel  checklista  [3 os-dni ~ 3 600 PLN]

## Sterowanie i kanały
- Gemini z rotacją kluczy — Klient wielu kluczy  cooldown na limitach  aliasy Gemini  [1 os-dni ~ 1 200 PLN]
- Agent operator + worker Windows — Kanał poleceń  sterowanie pulpitem (mysz/klawiatura/ekran/shell)  autostart  [5 os-dni ~ 6 000 PLN]
- Aplikacja na telefon (PWA) — Logowanie jednorazowym hasłem  polecenia  zatwierdzenia  status  wyłącznik awaryjny  [3 os-dni ~ 3 600 PLN]
- Jarvis + agenci biurowi — Agent nadrzędny i profile: secretary  researcher  sales  support  bookkeeper  analyst  [2 os-dni ~ 2 400 PLN]
- Wzrok operatora — Przekazywanie zrzutu ekranu do modelu wizyjnego  [2 os-dni ~ 2 400 PLN]
- Kanał Telegram — Odbiór i odpowiedzi Jarvisa przez webhook (allowlist czatu)  [1 os-dni ~ 1 200 PLN]

## Konektory biurowe
- Poczta (IMAP/SMTP) — Czytanie  czytanie wątków  wysyłka (za zatwierdzeniem)  [2 os-dni ~ 2 400 PLN]
- Kalendarz + eksport .ics — Wydarzenia  zakresy dat  eksport do Outlook/Google  [2 os-dni ~ 2 400 PLN]
- CRM + leady ze stron — Kontakty  szanse sprzedaży (etapy)  endpoint formularzy leadów  [3 os-dni ~ 3 600 PLN]
- Faktury (bookkeeper) — Numeracja  VAT  statusy  wydruk HTML/markdown  [3 os-dni ~ 3 600 PLN]
- Generowanie dokumentów — Pliki .docx/.html z markdownu bez zależności  [2 os-dni ~ 2 400 PLN]
- Analityk (CSV + KPI) — Analiza CSV i podsumowanie biznesowe z faktur/CRM  [2 os-dni ~ 2 400 PLN]
- Notatki / to-do — Lista zadań właściciela  [1 os-dni ~ 1 200 PLN]

## Niezawodność i bezpieczeństwo
- Dziennik audytu — Trwały zapis każdej akcji agenta (zgodność/kontrola)  [1 os-dni ~ 1 200 PLN]
- Harmonogram zadań — Zadania cykliczne (dziennie/tygodniowo/interwał)  [2 os-dni ~ 2 400 PLN]
- Baza wiedzy firmy (RAG) — Indeksowanie dokumentów  odpowiedzi z użyciem danych firmy  [2 os-dni ~ 2 400 PLN]
- Wyłącznik awaryjny — Globalna pauza wszystkich akcji agentów z telefonu  [1 os-dni ~ 1 200 PLN]

## Aplikacja snap2list
- Zdjęcie -> ogłoszenie (OLX/Allegro) — Backend wizyjny  generowanie opisu+ceny  wystawianie API/manualne  UI mobilne  [5 os-dni ~ 6 000 PLN]

## Podsumowanie
- Łączna pracochłonność: **76 osobodni**
- Szacunkowa wartość: **91 200 PLN netto**
