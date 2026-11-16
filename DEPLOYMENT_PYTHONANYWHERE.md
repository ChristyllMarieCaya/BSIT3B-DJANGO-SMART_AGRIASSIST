# Deploying SMART AGRIASSIST on PythonAnywhere

This guide walks through a complete deployment of the Django project on
PythonAnywhere, including Google Gemini AI, static/media files, and the
agricultural automation task.

The project uses **Django 5.0.14**. PythonAnywhere's **Python 3.12** runtime is
the recommended choice because Django 5.0 officially supports Python
3.10–3.12. Do not select a newer Python version for this project.

---

## 1. What you need

- A PythonAnywhere account (free or paid).
- The project folder (this repository) on your computer.
- Your Gemini API key from <https://aistudio.google.com/>.
- A strong Django secret key.

Generate a secret key locally or in a PythonAnywhere Bash console:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

> **Free accounts:** outbound internet requests must go through PythonAnywhere's
> proxy. Gemini calls can time out until `HTTPS_PROXY` is set (see
> [Troubleshooting](#11-troubleshooting)). Paid accounts have direct internet
> access and normally do not need this.

---

## 2. Create the web app

1. Log in to PythonAnywhere and open the **Web** tab.
2. Click **Add a new web app**.
3. Choose **Manual configuration** (not the Django wizard).
4. Select **Python 3.12**.
5. On the next screen, note the paths shown. They are usually:
   - Source code: `/home/CayaMae12/smart-agriassist`
   - Virtualenv: `/home/CayaMae12/.virtualenvs/smart-agri`
   - WSGI file: `/var/www/cayamae12_pythonanywhere_com_wsgi.py`

Replace `CayaMae12` with your PythonAnywhere username everywhere in this guide.

---

## 3. Upload the project

Open a **Bash console** on PythonAnywhere and create the project directory:

```bash
mkdir -p ~/smart-agriassist
```

### Option A — Upload a ZIP from your computer

On your computer, create a ZIP of the project **without** `.venv-1`,
`__pycache__`, `staticfiles`, and ideally without the live `.env` file. Then on
PythonAnywhere use **Files → Upload a file**, upload the ZIP, and unpack it:

```bash
cd ~/smart-agriassist
unzip ~/smart-agriassist.zip
```

### Option B — Git

If the project is in a Git repository:

```bash
cd ~
git clone https://github.com/YOUR-ACCOUNT/smart-agriassist.git
```

### Existing data

`db.sqlite3` is the development database. If you want the same users, crops,
diagnoses, and settings in production, upload it into the project root before
running migrations. Otherwise skip it and Django will create a fresh database.

---

## 4. Create the virtualenv and install dependencies

In the Bash console:

```bash
mkvirtualenv --python=/usr/bin/python3.12 smart-agri
cd ~/smart-agriassist
pip install --upgrade pip
pip install -r requirements.txt
```

If `mysqlclient` fails to build and you are using SQLite (the default), remove
or comment out the `mysqlclient` line in `requirements.txt` and install again:

```bash
pip install -r requirements.txt
```

`mysqlclient` is only needed when `DB_ENGINE=mysql`.

---

## 5. Configure environment variables

Create the production `.env` file:

```bash
cd ~/smart-agriassist
cp .env.example .env
nano .env
```

Set at least these values:

```dotenv
DJANGO_SECRET_KEY=<the-long-random-key-you-generated>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=USERNAME.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://USERNAME.pythonanywhere.com
SITE_URL=https://USERNAME.pythonanywhere.com

DB_ENGINE=sqlite
DB_NAME=db.sqlite3

GEMINI_API_KEY=<your-real-gemini-api-key>
GEMINI_MODEL=gemini-3.5-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_CONNECT_TIMEOUT_SECONDS=10
GEMINI_MAX_RETRIES=2
```

Notes:

- Keep `DJANGO_DEBUG=False` in production.
- `DJANGO_SECURE_SSL_REDIRECT=True` is the default when `DEBUG=False`; you do
  not need to add it unless you want to override the default.
- Never upload or commit the real `.env` file. It contains secrets.
- Save in nano with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

If you prefer a custom domain later, add it to `DJANGO_ALLOWED_HOSTS` and
`DJANGO_CSRF_TRUSTED_ORIGINS`.

---

## 6. Configure the WSGI file

1. Open the **Web** tab and click the WSGI configuration file link.
2. Delete the example contents.
3. Paste the contents of [`deploy/pythonanywhere_wsgi.py`](deploy/pythonanywhere_wsgi.py).
4. Replace `<USERNAME>` and the project path:

```python
PROJECT_HOME = '/home/CayaMae12/smart-agriassist'
SITE_HOST = 'CayaMae12.pythonanywhere.com'
```

5. Save the file.

The template sets `DJANGO_SETTINGS_MODULE=mysite.settings`, forces production
mode, and lets `mysite/settings.py` load the rest of the secrets from `.env`.

---

## 7. Run migrations and collect static files

Use the virtualenv Python explicitly:

```bash
cd ~/smart-agriassist
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

`collectstatic` copies the project's CSS, JavaScript, images, and vendor files
into `~/smart-agriassist/staticfiles`.

Test the Django configuration:

```bash
python manage.py check --deploy
```

Warnings about HSTS are normal if you have not enabled HSTS yet.

---

## 8. Configure static and media mappings

Static files are **not** served by Django in production. In the **Web** tab,
scroll to **Static files** and add two mappings:

| URL        | Directory                                        |
|------------|--------------------------------------------------|
| `/static/` | `/home/CayaMae12/smart-agriassist/staticfiles`    |
| `/media/`  | `/home/CayaMae12/smart-agriassist/media`          |

The `/media/` mapping is required for uploaded crop photos and AI diagnosis
images. Make sure the `media` directory exists and is writable:

```bash
mkdir -p ~/smart-agriassist/media
chmod 755 ~/smart-agriassist/media
```

Then click **Reload** at the top of the Web tab.

---

## 9. Verify the site and Gemini

Open `https://USERNAME.pythonanywhere.com/` and sign in.

To verify Gemini from the server:

```bash
cd ~/smart-agriassist
python manage.py shell
```

Paste:

```python
from apps.core import gemini
print(gemini.api_key_configured())
print(gemini.model_name())
print(gemini.connection_status(force=True))
print(gemini.generate_reply(__import__('django.contrib.auth').contrib.auth.get_user_model().objects.first(), 'Reply with the single word BANANA.', []))
```

Expected results:

- `True`
- your configured model name
- `{'state': 'connected', 'message': 'Gemini connection verified'}`
- a short reply such as `BANANA`

You can also open the **Agri AI Assistant** page; the status badge should show
that the connection is verified and the chat input should be enabled.

---

## 10. Schedule the automation task

The project includes a management command that runs weather monitoring, crop
stage updates, reminders, and alert generation.

In PythonAnywhere open **Tasks** and add a daily task:

```bash
cd /home/USERNAME/smart-agriassist && /home/USERNAME/.virtualenvs/smart-agri/bin/python manage.py run_agricultural_automations --once
```

Recommended schedule: once or twice per day. The command is designed for
one-shot execution with `--once`; do not run the continuous daemon mode on
PythonAnywhere.

The in-process automation thread is disabled automatically when
`DJANGO_DEBUG=False`. That is intentional: a PythonAnywhere web worker can be
recycled, and multiple workers would otherwise run duplicate cycles. The
Scheduled Task above is the production automation runner.

---

## 11. Troubleshooting

### `DisallowedHost`

Add the exact hostname to `DJANGO_ALLOWED_HOSTS` in `.env`, for example:

```dotenv
DJANGO_ALLOWED_HOSTS=USERNAME.pythonanywhere.com
```

Then reload the web app.

### `CSRF verification failed`

Add the full HTTPS origin to `DJANGO_CSRF_TRUSTED_ORIGINS`:

```dotenv
DJANGO_CSRF_TRUSTED_ORIGINS=https://USERNAME.pythonanywhere.com
```

### CSS, icons, or images are missing

- Confirm `python manage.py collectstatic --noinput` completed.
- Confirm the `/static/` mapping points to `staticfiles`, **not** `static`.
- Confirm the `/media/` mapping points to the project's `media` directory.
- Hard-refresh the browser after reloading the web app.

### Gemini times out on a free account

Free PythonAnywhere accounts route outbound traffic through a proxy. Add this
to `.env` and reload:

```dotenv
HTTPS_PROXY=http://proxy.server:3128
HTTP_PROXY=http://proxy.server:3128
```

If the proxy is not required (paid account), leave these unset. To bypass the
proxy for local hosts, you can also set:

```dotenv
NO_PROXY=127.0.0.1,localhost
```

Then repeat the verification in section 9.

### Gemini says the model is unavailable

Check `GEMINI_MODEL` in `.env`. Use a model that your API key can access. The
project's current default is `gemini-3.5-flash`; `gemini-2.5-flash` is a
fallback if that model is not enabled for your account.

### `no such table` or database errors

Run:

```bash
cd ~/smart-agriassist
python manage.py migrate
```

If you uploaded an existing `db.sqlite3`, make sure the file is in the project
root and readable by your user.

### `mysqlclient` installation error

You are using SQLite, so remove `mysqlclient` from `requirements.txt` and rerun
`pip install -r requirements.txt`. Only install it if you switch to MySQL.

### 500 error with no details

Set `DJANGO_DEBUG=True` temporarily in `.env`, reload, and reproduce the error.
**Set it back to `False` immediately afterward.** Also check the error log link
on the Web tab.

### Uploaded images return 404

Confirm the `/media/` static mapping exists and that `MEDIA_ROOT` points to
`/home/USERNAME/smart-agriassist/media`. Files uploaded before the mapping was
added are still on disk; just reload the app.

---

## 12. Updating the deployment

After changing code locally:

1. Upload the changed files (or `git pull` on PythonAnywhere).
2. Activate the virtualenv if needed: `workon smart-agri`.
3. Run:

```bash
cd ~/smart-agriassist
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

4. Click **Reload** on the Web tab.

---

## 13. Production checklist

- [ ] `DJANGO_DEBUG=False`
- [ ] Unique `DJANGO_SECRET_KEY` set
- [ ] `DJANGO_ALLOWED_HOSTS` contains the PythonAnywhere hostname
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` contains the HTTPS origin
- [ ] `SITE_URL` uses `https://`
- [ ] `GEMINI_API_KEY` set and verified
- [ ] `python manage.py migrate` completed
- [ ] `python manage.py collectstatic --noinput` completed
- [ ] `/static/` and `/media/` mappings configured
- [ ] Superuser created
- [ ] Automation task scheduled
- [ ] Real `.env` file is not committed or publicly downloadable
- [ ] Backup of `db.sqlite3` and `media/` scheduled
