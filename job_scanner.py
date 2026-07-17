"""
Job scanner semanal — perfil: legal counsel / public international law / IHL /
weapons law / researcher / AI governance.

Busca en Indeed, LinkedIn y Google Jobs vía JobSpy, deduplica lo ya visto,
puntúa cada oferta contra el perfil y envía un informe HTML por email (Brevo).

Secrets necesarios (GitHub Actions -> Settings -> Secrets -> Actions):
  BREVO_API_KEY  - API key de Brevo (Settings > SMTP & API > API Keys)
  EMAIL_FROM     - remitente verificado en Brevo, ej. "alvaro@tudominio.com"
  EMAIL_TO       - destinatario(s), separados por coma

Uso local de prueba:  DRY_RUN=1 python job_scanner.py   (no envía email)
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

try:
    from jobspy import scrape_jobs
except ImportError:  # permite validar el resto del script sin la librería
    scrape_jobs = None

# v2 — organismos internacionales (ICRC, ONU vía ReliefWeb + enlaces NATO/EEAS/OSCE)
from org_scanner import fetch_reliefweb, org_links_html

# ----------------------------------------------------------------------
# 1. BÚSQUEDAS  (término, ubicación, solo_remoto)
#    - "Spain": ofertas ubicadas en España.
#    - remoto=True + "European Union": remotas europeas que pueden permitir España.
# ----------------------------------------------------------------------
# Todas las búsquedas son remotas (requisito: solo full remoto ES/UE).
SEARCHES = [
    # --- Public international law / IHL / weapons law (núcleo del perfil) ---
    ("public international law legal adviser", "Spain", True),
    ("public international law legal adviser", "European Union", True),
    ("international humanitarian law", "European Union", True),
    ("international humanitarian law legal officer", "Spain", True),
    ("weapons law arms control legal", "European Union", True),
    ("disarmament non-proliferation legal", "European Union", True),
    ("legal adviser international law", "European Union", True),
    # --- Researcher ---
    ("legal researcher international law", "Spain", True),
    ("research fellow international law human rights", "European Union", True),
    ("researcher AI governance policy", "European Union", True),
    # --- Extras basados en el CV ---
    ("legal officer international organisation", "Spain", True),
    ("human rights legal officer", "European Union", True),
    ("regulatory counsel EU AI Act", "European Union", True),
    ("legal counsel data protection GDPR", "European Union", True),
    # --- Perfil comercial actual (transición) ---
    ("legal counsel remote", "Spain", True),
    ("commercial legal counsel", "European Union", True),
]

SITES = ["indeed", "linkedin", "google"]
HOURS_OLD = 168            # última semana
RESULTS_PER_SEARCH = 25
COUNTRY_INDEED = "Spain"
SCORE_THRESHOLD = 3        # sube este número si llega mucho ruido
MAX_JOBS_IN_EMAIL = 40

# ----------------------------------------------------------------------
# 2. SCORING contra el perfil (título pesa doble que la descripción)
# ----------------------------------------------------------------------
KEYWORDS = {
    "public international law": 6,
    "international humanitarian": 6,
    "international law": 4,
    "weapons": 4,
    "arms control": 4,
    "disarmament": 4,
    "non-proliferation": 4,
    "human rights": 4,
    "humanitarian": 3,
    "legal adviser": 4,
    "legal advisor": 4,
    "legal counsel": 4,
    "legal officer": 4,
    "researcher": 3,
    "research fellow": 3,
    "policy officer": 3,
    "in-house": 3,
    "gdpr": 3,
    "data protection": 3,
    "ai act": 3,
    "ai governance": 3,
    "regulatory": 2,
    "compliance": 2,
    "contract": 2,
    "commercial": 2,
    "policy": 2,
    "united nations": 4,
    "nato": 4,
    "icrc": 5,
    "red cross": 4,
    "osce": 4,
    "european commission": 3,
    # geografía / idiomas (encaje con España)
    "remote": 2,
    "spain": 3,
    "madrid": 2,
    "barcelona": 2,
    "french": 2,
    "spanish": 2,
}

# ----------------------------------------------------------------------
# 3. FILTROS DE EXCLUSIÓN (requisitos de Alvaro)
# ----------------------------------------------------------------------
MIN_YEARS_EXCLUDE = 4      # fuera si piden 4+ años de experiencia

# Junior / apoyo (título o descripción)
EXCLUDE_GENERIC = [
    "paralegal", "internship", "intern ", "prácticas", "practicas",
    "becario", "becaria", "trainee", "secretary", "assistant to",
]

# Docencia / academia (se comprueba sobre todo en el TÍTULO)
EXCLUDE_ACADEMIC = [
    "teacher", "professor", "lecturer", "faculty", "instructor", "tutor",
    "teaching", "docente", "profesor", "catedrátic", "postdoc", "post-doc",
    "phd student", "ph.d student", "doctoral", "university", "universidad",
    "academic", "académic",
]

# Colegiación / bar admission (título o descripción)
EXCLUDE_BAR = [
    "bar admission", "admitted to the bar", "member of the bar",
    "admission to the bar", "called to the bar", "state bar", "bar exam",
    "bar association", "passed the bar", "bar qualified", "qualified to the bar",
    "admitted to practice", "license to practice law", "licensed to practice law",
    "colegiad", "colegio de abogados", "colegiación",
]

# Restricción geográfica incompatible con remoto desde España
EXCLUDE_GEO = [
    "must be based in the united states", "us-based only", "based in the us only",
    "authorized to work in the united states", "u.s. work authorization",
    "must reside in the united states", "us work authorization",
    "eligible to work in the us", "must be located in the united states",
    "canada only", "based in the uk only", "uk-based only", "onsite in",
]

# Señales de híbrido / presencial (rompen el requisito de FULL remoto)
HYBRID_ONSITE = [
    "hybrid", "híbrido", "hibrido", "on-site", "onsite", "on site",
    "presencial", "in-office", "in office", "days in the office",
    "days per week in the office", "días en la oficina", "relocation",
]

# Señales de remoto pleno
REMOTE_POSITIVE = [
    "remote", "fully remote", "100% remote", "remote-first", "work from home",
    "home-based", "home based", "teletrabajo", "en remoto", "remoto", "anywhere",
]

SEEN_FILE = Path("seen_jobs.json")


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except json.JSONDecodeError:
            return set()
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=1))


def _clean(x) -> str:
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


def requires_senior_experience(text: str, threshold: int = MIN_YEARS_EXCLUDE) -> bool:
    """True si TODAS las menciones de años de experiencia son >= threshold.
    Rangos (p.ej. '2-4 años') usan el límite inferior; así '2-4' NO se descarta."""
    t = text.lower()
    reqs = []
    # rangos: "2-4 years" / "2 a 4 años" -> límite inferior
    for m in re.finditer(r"(\d{1,2})\s*(?:-|–|to|a)\s*\d{1,2}\s*\+?\s*(?:years?|yrs?|años?|año)", t):
        _add_if_experience(t, m, int(m.group(1)), reqs)
    # sueltos: "5+ years" / "mínimo 4 años" (número pegado a la unidad)
    for m in re.finditer(r"(?<![\d\-–])(\d{1,2})\s*\+?\s*(?:years?|yrs?|años?|año)", t):
        _add_if_experience(t, m, int(m.group(1)), reqs)
    return bool(reqs) and min(reqs) >= threshold


def _add_if_experience(text: str, match, value: int, out: list) -> None:
    window = text[max(0, match.start() - 45): match.end() + 45]
    if "experien" in window or "experience" in window:
        out.append(value)


def _has(text: str, terms) -> bool:
    return any(t in text for t in terms)


def excluded(row) -> bool:
    title = _clean(row.get("title")).lower()
    desc = _clean(row.get("description")).lower()
    loc = _clean(row.get("location")).lower()
    both = f"{title} {desc}"
    if _has(both, EXCLUDE_GENERIC):
        return True
    if _has(title, EXCLUDE_ACADEMIC):
        return True
    if _has(both, EXCLUDE_BAR):
        return True
    if _has(f"{both} {loc}", EXCLUDE_GEO):
        return True
    if requires_senior_experience(both):
        return True
    return False


def is_full_remote(row) -> bool:
    """Solo full remoto: señal de remoto presente y sin marcas de híbrido/presencial."""
    title = _clean(row.get("title")).lower()
    desc = _clean(row.get("description")).lower()
    loc = _clean(row.get("location")).lower()
    text = f"{title} {desc} {loc}"
    if _has(text, HYBRID_ONSITE):
        return False
    return bool(row.get("is_remote")) or _has(text, REMOTE_POSITIVE)


def score_job(row) -> int:
    title = _clean(row.get("title")).lower()
    desc = _clean(row.get("description")).lower()
    score = 0
    for kw, w in KEYWORDS.items():
        if kw in title:
            score += w * 2   # coincidencia en el título pesa doble
        elif kw in desc:
            score += w
    return score


def run_searches() -> pd.DataFrame:
    frames = []
    if scrape_jobs is None:
        print("[warn] jobspy no instalado; solo se usará ReliefWeb (ONU/ICRC)")
    for term, location, remote in ([] if scrape_jobs is None else SEARCHES):
        try:
            df = scrape_jobs(
                site_name=SITES,
                search_term=term,
                google_search_term=f"{term} jobs {location}",
                location=location,
                is_remote=remote,
                results_wanted=RESULTS_PER_SEARCH,
                hours_old=HOURS_OLD,
                country_indeed=COUNTRY_INDEED,
                description_format="markdown",
            )
            n = 0 if df is None else len(df)
            if n:
                df["search"] = term
                frames.append(df)
            print(f"[ok] {term} ({location}) -> {n}")
        except Exception as e:  # una búsqueda que falla no tumba el resto
            print(f"[warn] fallo en '{term}': {e}", file=sys.stderr)
    # v2: añade ofertas de ONU/ICRC vía ReliefWeb (API), mismo esquema
    rw = fetch_reliefweb()
    if rw:
        frames.append(pd.DataFrame(rw))

    if not frames:
        return pd.DataFrame()
    jobs = pd.concat(frames, ignore_index=True)
    jobs = jobs.dropna(subset=["job_url"]).drop_duplicates(subset=["job_url"])
    return jobs


def build_email(jobs: pd.DataFrame) -> str:
    rows = []
    for _, j in jobs.iterrows():
        salary = ""
        if pd.notna(j.get("min_amount")):
            cur = _clean(j.get("currency"))
            salary = f" · {float(j['min_amount']):.0f}–{float(j.get('max_amount') or 0):.0f} {cur}"
        loc = _clean(j.get("location"))
        remote = " · 🌍 remoto" if j.get("is_remote") else ""
        rows.append(
            "<tr><td style='padding:10px;border-bottom:1px solid #eee'>"
            f"<a href='{_clean(j.get('job_url'))}' style='font-weight:bold;color:#1a4d8f;text-decoration:none'>"
            f"{_clean(j.get('title')) or '(sin título)'}</a><br>"
            f"{_clean(j.get('company'))} · {loc}{remote}{salary}<br>"
            f"<span style='color:#888;font-size:12px'>encaje {int(j['score'])} · "
            f"vía {_clean(j.get('site'))} · búsqueda: {_clean(j.get('search'))}</span>"
            "</td></tr>"
        )
    date = datetime.now().strftime("%d/%m/%Y")
    return (
        "<div style='font-family:sans-serif;max-width:640px'>"
        f"<h2 style='color:#1a4d8f'>Informe semanal de ofertas — {date}</h2>"
        f"<p>{len(jobs)} ofertas nuevas ordenadas por encaje con el perfil.</p>"
        f"<table style='font-size:14px;width:100%;border-collapse:collapse'>{''.join(rows)}</table>"
        f"{org_links_html()}"
        "<p style='color:#aaa;font-size:11px;margin-top:16px'>Generado automáticamente. "
        "Ajusta búsquedas y umbral en job_scanner.py.</p></div>"
    )


def send_brevo(html: str, n_jobs: int) -> None:
    api_key = os.environ["BREVO_API_KEY"]
    to = [{"email": e.strip()} for e in os.environ["EMAIL_TO"].split(",") if e.strip()]
    week = datetime.now().isocalendar()[1]
    payload = {
        "sender": {"email": os.environ["EMAIL_FROM"], "name": "Job Bot"},
        "to": to,
        "subject": f"🔎 {n_jobs} ofertas nuevas para el perfil legal — semana {week}",
        "htmlContent": html,
    }
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "content-type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    print(f"[ok] email enviado ({r.status_code}) a {len(to)} destinatario(s)")


def main():
    dry_run = os.environ.get("DRY_RUN") == "1"
    seen = load_seen()
    jobs = run_searches()
    if jobs.empty:
        print("Sin resultados esta semana.")
        return

    jobs = jobs[~jobs["job_url"].isin(seen)].copy()
    if jobs.empty:
        print("Todo ya visto; no se envía email.")
        return

    # --- Filtros de Alvaro: fuera 4+ años, bar, academia, geo; solo full remoto ---
    antes = len(jobs)
    jobs = jobs[~jobs.apply(excluded, axis=1)]
    jobs = jobs[jobs.apply(is_full_remote, axis=1)]
    print(f"[filtros] {antes} -> {len(jobs)} tras excluir (experiencia/bar/academia/geo) "
          f"y exigir full remoto")
    if jobs.empty:
        print("Nada pasa los filtros; no se envía email.")
        seen.update(jobs["job_url"].tolist())
        save_seen(seen)
        return

    jobs = jobs.copy()
    jobs["score"] = jobs.apply(score_job, axis=1)
    jobs = jobs[jobs["score"] >= SCORE_THRESHOLD]
    jobs = jobs.sort_values("score", ascending=False).head(MAX_JOBS_IN_EMAIL)

    if jobs.empty:
        print("Nada supera el umbral de encaje; no se envía email.")
    elif dry_run:
        Path("preview.html").write_text(build_email(jobs), encoding="utf-8")
        print(f"[dry-run] {len(jobs)} ofertas -> preview.html (sin enviar)")
    else:
        send_brevo(build_email(jobs), len(jobs))

    # marca como vistas todas las nuevas encontradas
    seen.update(jobs["job_url"].tolist())
    save_seen(seen)


if __name__ == "__main__":
    main()
