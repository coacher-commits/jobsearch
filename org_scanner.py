"""
v2 — organismos internacionales (ICRC, ONU, NATO, EEAS, OSCE).

Estos organismos NO publican en LinkedIn/Indeed, así que se cubren aparte:

  * ICRC y el sistema ONU  -> API pública de ReliefWeb (JSON, gratis, oficial de OCHA).
                              Scanning real y automático.
  * NATO / EEAS / OSCE     -> portales propios con JavaScript y sin feed limpio.
                              Scrapearlos a ciegas sería frágil, así que se añaden
                              como enlaces de búsqueda filtrada en cada email
                              (un clic, cero mantenimiento).

Devuelve filas con el MISMO esquema que JobSpy para poder fusionarlas y puntuarlas
con la misma lógica de job_scanner.py.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

# ----------------------------------------------------------------------
# ReliefWeb — ICRC + sistema ONU + ONGs de DIH / derechos humanos
# Doc: https://apidoc.reliefweb.int/  (desde nov-2025 requiere appname aprobado)
# ----------------------------------------------------------------------
RELIEFWEB_URL = "https://api.reliefweb.int/v2/jobs"

# Términos legales que deben aparecer EN EL TÍTULO (mantiene la señal alta)
RW_TITLE_TERMS = [
    "legal", "law", "counsel", "adviser", "advisor",
    "human rights", "humanitarian", "protection", "researcher", "policy",
]

# Fuentes prioritarias (se resaltan; ReliefWeb las etiqueta por 'source')
RW_PRIORITY_SOURCES = {"icrc", "un", "ohchr", "undp", "unhcr", "iom", "unicef"}


def _looks_remote(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ("remote", "home-based", "home based", "telecommut"))


def fetch_reliefweb(days: int = 8, limit: int = 80) -> list[dict]:
    """Devuelve ofertas legales recientes del sistema ONU / ICRC vía ReliefWeb."""
    appname = os.environ.get("RELIEFWEB_APPNAME", "job-bot-personal")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT00:00:00+00:00"
    )
    lucene = " OR ".join(f'"{t}"' for t in RW_TITLE_TERMS)
    payload = {
        "appname": appname,
        "limit": limit,
        "profile": "list",
        "preset": "latest",
        "query": {"value": lucene, "fields": ["title"], "operator": "OR"},
        "filter": {"field": "date.created", "value": {"from": since}},
        "fields": {
            "include": [
                "title", "url", "source.name", "source.shortname",
                "country.name", "city.name", "date.closing", "body",
            ]
        },
    }
    try:
        r = requests.post(RELIEFWEB_URL, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:  # no debe tumbar el resto del bot
        print(f"[warn] ReliefWeb falló: {e}")
        return []

    rows = []
    for item in data:
        f = item.get("fields", {})
        title = f.get("title", "")
        source = (f.get("source") or [{}])[0]
        company = source.get("name") or source.get("shortname") or "ONU/ICRC"
        countries = ", ".join(c.get("name", "") for c in (f.get("country") or []))
        body = f.get("body", "") or ""
        rows.append(
            {
                "title": title,
                "company": company,
                "location": countries,
                "is_remote": _looks_remote(f"{title} {countries} {body[:400]}"),
                "job_url": f.get("url", ""),
                "site": "reliefweb",
                "description": body,
                "search": "ONU/ICRC (ReliefWeb)",
                "min_amount": None,
                "max_amount": None,
                "currency": None,
            }
        )
    print(f"[ok] ReliefWeb (ONU/ICRC) -> {len(rows)}")
    return rows


# ----------------------------------------------------------------------
# Enlaces de búsqueda filtrada (portales sin API fiable)
# Se incluyen SIEMPRE al final del email: un clic para revisar cada organismo.
# ----------------------------------------------------------------------
ORG_LINKS = [
    ("ICRC — careers (búsqueda 'legal')", "https://careers.icrc.org/search/?q=legal"),
    ("ONU — UN Careers (filtra Job Family: Legal)", "https://careers.un.org/"),
    ("NATO — vacantes International Staff", "https://www.nato.int/en/work-with-us/careers/vacancies"),
    ("EEAS — vacantes (contract agents, SNE, prácticas)", "https://www.eeas.europa.eu/eeas/vacancies_en"),
    ("OSCE — vacancies (Secretariat + misiones)", "https://vacancies.osce.org/"),
]


def org_links_html() -> str:
    items = "".join(
        f"<li style='margin:4px 0'><a href='{url}' "
        f"style='color:#1a4d8f;text-decoration:none'>{name}</a></li>"
        for name, url in ORG_LINKS
    )
    return (
        "<div style='margin-top:22px;padding:14px;background:#f6f8fb;border-radius:8px'>"
        "<h3 style='margin:0 0 6px;color:#1a4d8f;font-size:15px'>"
        "Revisión manual — organismos sin scraping fiable</h3>"
        "<p style='margin:0 0 8px;font-size:13px;color:#555'>"
        "Estos portales usan JavaScript y no ofrecen feed estable; enlaces directos "
        "a su búsqueda de perfiles legales:</p>"
        f"<ul style='margin:0;padding-left:18px;font-size:14px'>{items}</ul></div>"
    )
