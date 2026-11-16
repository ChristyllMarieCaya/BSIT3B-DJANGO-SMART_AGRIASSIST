# SMART AGRIASSIST

An intelligent farm management system built with Django. It combines crop
growth tracking, weather monitoring and severe-weather advisories, AI-assisted
crop diagnosis, a crop reference catalog, notifications, and automated crop
care reminders.

**Project team**

- CAYA, CHRISTYLL MARIE L.
- BULAHAN, MAILEN
- ADRIAS, IRISH ANN

---

## Features

- **Dashboard** — active crops, upcoming tasks, recent diagnoses, live weather,
  notifications, and recent AI conversations.
- **Agri AI Assistant** — Google Gemini powered multi-turn chat with farm
  context, crop-image uploads, and automatic diagnosis records.
- **Crop growth tracking** — stages, timelines, care activities, and harvest
  estimates.
- **Weather & alerts** — Open-Meteo forecasts, optional PAGASA advisories, and
  configurable severe-weather thresholds.
- **Crop catalog** — searchable read-only reference information.
- **Notifications** — in-app alerts, unread counts, filters, and optional email
  or browser notifications.
- **Automation** — a management command for weather checks, crop-stage updates,
  and reminder generation.
- **Responsive UI** — full desktop layout plus a mobile drawer navigation and
  mobile-specific layout adjustments.

---

## Requirements

- Python 3.10–3.12 (Python 3.12 recommended; Django 5.0.14)
- pip
- SQLite (default, no setup required) or MySQL/PostgreSQL
- A Google Gemini API key for live AI responses

---

## Local setup

1. **Create and activate a virtual environment**

   ```bash
   python -m venv .venv
   ```

   Windows (PowerShell):

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Create your environment file**

   ```bash
   copy .env.example .env
   ```

   On macOS/Linux use `cp .env.example .env`. Then edit `.env` and set at least
   `DJANGO_SECRET_KEY` and `GEMINI_API_KEY`. For local development keep
   `DJANGO_DEBUG=True`.

4. **Apply migrations and create an account**

   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```

5. **Run the development server**

   ```bash
   python manage.py runserver
   ```

   Open <http://127.0.0.1:8000/>.

6. **Optional: run one automation cycle**

   ```bash
   python manage.py run_agricultural_automations --once
   ```

---

## Environment configuration

All secrets and deployment-specific values are read from `.env` in the project
root. See [`.env.example`](.env.example) for the full list and comments.

Important variables:

| Variable | Purpose |
|----------|---------|
| `DJANGO_SECRET_KEY` | Secret key; required when `DEBUG=False` |
| `DJANGO_DEBUG` | `True` locally, `False` in production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins |
| `SITE_URL` | Absolute site URL used in notifications |
| `ENABLE_BACKGROUND_SCHEDULER` | In-process automation; defaults to `DJANGO_DEBUG` |
| `DB_ENGINE` | `sqlite` (default), `mysql`, or `postgres` |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | Gemini model name |
| `EMAIL_*` | Optional SMTP settings for email alerts |

Never commit the real `.env` file. It is already excluded by `.gitignore`.

---

## Tests and checks

```bash
python manage.py check
python manage.py test
```

The project also includes a `pytest.ini` for pytest-based runs.

---

## Deploying to PythonAnywhere

A complete step-by-step guide is available in
[`DEPLOYMENT_PYTHONANYWHERE.md`](DEPLOYMENT_PYTHONANYWHERE.md). It covers:

- uploading the project and creating a Python 3.12 virtualenv
- installing dependencies and configuring `.env`
- the ready-to-use WSGI template in `deploy/pythonanywhere_wsgi.py`
- migrations, `collectstatic`, and static/media mappings
- verifying Google Gemini
- scheduling the automation command
- troubleshooting common deployment errors

---

## Project structure

```
mysite/              Django project settings, URLs, and WSGI
apps/core/           Dashboard, AI assistant, weather, notifications, automation
apps/crops/          Crop tracking, growth stages, and reminders
apps/catalog/        Crop reference catalog
apps/info/           Guidelines and notification models
templates/           Django templates (theme, auth, core pages, crops, catalog)
static/css/          Tabler overrides, app theme, and mobile-only styles
static/js/           Theme and application scripts
deploy/              Deployment templates
```
