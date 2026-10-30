# invoapi Python SDK

Python-Client für die [invoapi.de](https://invoapi.de) E-Rechnungs-API: **XRechnung, ZUGFeRD / Factur-X, EN 16931, UBL, CII und Peppol** erzeugen, gegen die offiziellen Regelwerke prüfen, umwandeln und auslesen.

- Python 3.9 oder neuer, **keine Abhängigkeiten** (nur die Standardbibliothek)
- Jede erzeugte Rechnung wird mit dem offiziellen KoSIT-Validator geprüft
- Automatische Wiederholung bei Tempolimit (429) und kurzzeitigen Ausfällen (5xx)
- Vollständig typisiert (`py.typed`)

> **English:** Python client for the [invoapi.de](https://invoapi.de) e-invoicing API. Create XRechnung, ZUGFeRD / Factur-X, EN 16931, UBL, CII and Peppol invoices, validate them against the official rule sets (KoSIT), convert and parse them. Python 3.9+, no dependencies. Install with `pip install invoapi`; see the [API documentation](https://invoapi.de/docs) for all invoice fields.

## Installation

```bash
pip install invoapi
```

Den API-Schlüssel finden Sie im [Dashboard](https://invoapi.de/dashboard) unter **API-Schlüssel**. Der Client liest ihn aus der Umgebungsvariable `INVOAPI_API_KEY`, oder Sie übergeben ihn direkt: `invoapi.Client("inv_live_…")`.

## Schnellstart: XRechnung erzeugen

```python
import invoapi

client = invoapi.Client()   # liest INVOAPI_API_KEY

rechnung = client.generate({
    "invoice_number": "RE-2026-0001",
    "issue_date": "2026-10-28",
    "due_date": "2026-11-27",
    "currency": "EUR",
    "buyer_reference": "04011000-12345-34",   # Leitweg-ID, Pflicht bei XRechnung an Behörden
    "seller": {
        "name": "Muster GmbH", "street": "Musterstraße 1", "postal_code": "10115",
        "city": "Berlin", "country_code": "DE", "vat_id": "DE123456789",
        "email": "rechnung@muster.de", "phone": "+49 30 1234567",
    },
    "buyer": {
        "name": "Beispiel GmbH", "street": "Teststraße 10", "postal_code": "20095",
        "city": "Hamburg", "country_code": "DE", "email": "kreditoren@beispiel.de",
    },
    "items": [
        {"name": "Beratung", "quantity": 8, "unit": "HUR", "unit_price": 145, "vat_rate": 19},
    ],
    "payment": {"means_code": "58", "iban": "DE02120300000000202051"},
}, format="xrechnung")

if rechnung.is_valid:
    rechnung.save()                      # RE-2026-0001.xml
    print(rechnung.totals["payable"])    # "1380.40"
```

Beträge dürfen auch `Decimal` sein, Datumsangaben `datetime.date`. Alle Felder der Rechnung beschreibt die [API-Dokumentation](https://invoapi.de/docs).

## ZUGFeRD-PDF

```python
pdf = client.generate(daten, format="zugferd", output="pdf", profile="en16931")
pdf.save("RE-2026-0001.pdf")   # PDF/A-3 mit eingebettetem XML
```

## Eingehende E-Rechnung prüfen

```python
from pathlib import Path

bericht = client.validate(Path("eingang.xml"))   # Pfad, bytes oder XML-Text; auch ZUGFeRD-PDF

if not bericht.is_valid:
    for fehler in bericht.errors:
        print(f"{fehler['rule']}: {fehler['message']}")   # z. B. "BR-DE-15: Leitweg-ID fehlt"
```

`is_valid` ist nur dann `True`, wenn ein offizielles Regelwerk tatsächlich gelaufen ist.

## Auslesen, erkennen, umwandeln, rechnen

```python
daten  = client.parse(xml_oder_pdf)          # Rechnung als dict: Verkäufer, Käufer, Positionen, Summen
art    = client.detect(xml_oder_pdf)         # {"format": "xrechnung", "syntax": "ubl", ...}
cii    = client.convert(ubl_xml, "xml", format="xrechnung", syntax="cii")
pdf    = client.convert(ubl_xml, "pdf", format="zugferd")   # XRechnung → ZUGFeRD-PDF
html   = client.render(xml_oder_pdf, "html")                # lesbare Ansicht für Menschen (bytes)
summen = client.calculate(daten)["totals"]                  # kostenlos, zählt nicht aufs Kontingent
```

## Fehlerbehandlung

Jede Ablehnung löst eine Ausnahme mit der verständlichen Meldung der API aus:

| Ausnahme | Wann | Was tun |
|---|---|---|
| `invoapi.InvalidRequestError` | Rechnung oder Dokument fehlerhaft (400/422) | `details` nennt die Felder |
| `invoapi.AuthenticationError` | Schlüssel falsch, E-Mail unbestätigt, Konto gesperrt | Schlüssel im Dashboard prüfen |
| `invoapi.QuotaExhaustedError` | Gratis-Kontingent aufgebraucht (402) | Tarif wählen: invoapi.de/preise |
| `invoapi.RateLimitError` | Zu viele Aufrufe (429), nach den Wiederholungen | `retry_after` Sekunden warten |
| `invoapi.ServiceUnavailableError` | Dienst kurz nicht erreichbar (5xx) | später erneut versuchen |
| `invoapi.APIConnectionError` | Keine Verbindung (DNS, TLS, Timeout) | Netzwerk prüfen |

Alle erben von `invoapi.InvoapiError` mit `http_status`, `code` und `request_id`. Die Request-ID hilft uns bei Support-Anfragen.

```python
try:
    rechnung = client.generate(daten)
except invoapi.InvalidRequestError as fehler:
    print(fehler, fehler.details)
except invoapi.InvoapiError as fehler:
    log.error("invoapi: %s (%s)", fehler, fehler.request_id)
```

## Optionen

```python
client = invoapi.Client(
    api_key,
    timeout=90,       # Sekunden pro Anfrage
    max_retries=2,    # Wiederholungen bei 429/5xx, 0 schaltet sie ab
)
```

## Tests

```bash
pip install -e . pytest
pytest -m "not integration"                       # ohne Netzwerk
INVOAPI_API_KEY=inv_… pytest -m integration       # gegen die echte API, verbraucht Kontingent
```

## Lizenz

MIT
