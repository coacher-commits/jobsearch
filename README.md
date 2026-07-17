# Job Bot — informe semanal de ofertas legales

Escanea cada lunes Indeed, LinkedIn y Google Jobs con búsquedas adaptadas al perfil
(public international law, IHL, weapons law/arms control, researcher, AI governance,
data protection y legal counsel comercial), deduplica lo ya visto, puntúa cada oferta
contra el perfil y envía las mejores por email vía Brevo.

**v2 — organismos internacionales:** además escanea **ICRC y el sistema ONU** vía la
API pública de ReliefWeb (OCHA), y añade en cada email enlaces directos de búsqueda
filtrada a **NATO, EEAS y OSCE** (sus portales usan JavaScript y no tienen feed fiable,
así que se cubren con un clic en vez de scraping frágil).

## Estructura de archivos

```
job_scanner.py        # scanner principal (JobSpy + scoring + email)
org_scanner.py        # v2: ReliefWeb (ONU/ICRC) + enlaces NATO/EEAS/OSCE
requirements.txt
README.md
.github/
  workflows/
    job-scan.yml
```

## Puesta en marcha (~10 min)

1. **Crea un repo privado en GitHub** y sube estos archivos manteniendo la estructura de arriba
   (importante que `job-scan.yml` quede dentro de `.github/workflows/`).

2. **Consigue tu API key de Brevo**: app.brevo.com → Settings → SMTP & API → API Keys → Generate.
   Verifica también un remitente en Senders, Domains & Dedicated IPs (el `EMAIL_FROM`).

3. **Añade los secrets en GitHub**: repo → Settings → Secrets and variables → Actions → New repository secret:
   - `BREVO_API_KEY` — la key del paso 2
   - `EMAIL_FROM` — `hola@nortecapital.es` (remitente verificado en Brevo)
   - `EMAIL_TO` — `emma.gonzales-puell@outlook.com` (o varios separados por coma)
   - `RELIEFWEB_APPNAME` *(opcional)* — ver "v2" abajo. Si no lo pones, usa un valor por
     defecto; recomendado registrarlo para evitar límites de la API.

4. **Pruébalo**: pestaña Actions → "Weekly job scan" → Run workflow.
   Si todo va bien, el email llega en unos minutos. La primera vez enviará bastantes
   ofertas; después solo las nuevas.

A partir de ahí corre solo **cada lunes a las 08:00** (hora española). Es gratis:
GitHub Actions da 2.000 min/mes en repos privados y esto gasta ~5 min/semana.

## Prueba en local (opcional)

```bash
pip install -r requirements.txt
DRY_RUN=1 python job_scanner.py   # busca de verdad pero NO envía email; genera preview.html
```

## Ajustes rápidos

- **Búsquedas**: edita la lista `SEARCHES` en `job_scanner.py` (término, ubicación, solo_remoto).
- **Umbral de encaje**: `SCORE_THRESHOLD = 3` — súbelo si llega mucho ruido.
- **Pesos del scoring**: diccionario `KEYWORDS` (una coincidencia en el título puntúa el doble).
- **Frecuencia**: cambia el `cron` en `job-scan.yml`
  (`"0 6 * * 1,4"` = lunes y jueves; `"0 6 */3 * *"` ≈ cada 3 días).

## v2 — organismos internacionales (ICRC, ONU, NATO, EEAS, OSCE)

- **ICRC + sistema ONU:** se escanean de verdad con la **API de ReliefWeb**
  (`org_scanner.py`), gratis y sin scraping. Coge ofertas legales/DIH/derechos humanos
  publicadas la última semana y las mezcla en el mismo ranking.
- **Appname de ReliefWeb:** desde noviembre 2025 la API pide un `appname` aprobado
  (gratis). Rellena [este formulario](https://apidoc.reliefweb.int/) → "Request an
  appname", y guarda el valor como secret `RELIEFWEB_APPNAME`. Mientras tanto funciona
  con un valor por defecto, pero puede tener límites de uso.
- **NATO, EEAS y OSCE:** sus portales usan JavaScript y no ofrecen feed estable, así que
  scrapearlos sería frágil y se rompería a menudo. En su lugar, cada email incluye un
  bloque de **enlaces de búsqueda filtrada** (un clic) a cada organismo. Si en el futuro
  quieres scraping real de estos tres, habría que usar un navegador headless
  (Playwright), que ya es un proyecto mayor.

## Limitaciones conocidas

- **LinkedIn** bloquea rápido sin proxies; si una búsqueda falla, el script lo registra
  como aviso y continúa con Indeed y Google (los más fiables). No tumba el resto.
- **Organismos internacionales** (ICRC, ONU, NATO, EEAS, OSCE) muchas veces **no publican**
  en LinkedIn/Indeed. Para cubrirlos bien conviene añadir en una v2 sus career pages o
  agregadores como UNjobs / Impactpool / ReliefWeb.
- El scoring es por palabras clave: es un buen primer filtro, no un juicio experto.
  Revisa el informe y ajusta `KEYWORDS` según lo que llegue.
