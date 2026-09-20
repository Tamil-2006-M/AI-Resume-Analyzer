# Deployment Guide

How to put the AI Resume Analyzer on the internet so you can put a live link
on your resume.

---

## Before you deploy: the three rules

**1. Turn debug mode off.**

```
FLASK_DEBUG=False
```

With `FLASK_DEBUG=True`, Flask serves an interactive Python console in the
browser whenever an error occurs. Anyone who can reach your site can then run
code on your server. This is the single most common way a student project gets
compromised.

**2. Generate a fresh `SECRET_KEY`.**

```powershell
python -c "import secrets; print(secrets.token_hex(24))"
```

Never reuse the one from your laptop, and never commit it.

**3. Do not use the development server.**

`python app.py` starts Flask's built-in server, which handles one request at a
time and is not hardened. Use **gunicorn** (Linux) or **waitress** (Windows).
That is what `wsgi.py` and `Procfile` are for.

---

## Option 1: Render (recommended - free tier, easiest)

Render builds straight from GitHub and gives you an HTTPS URL.

### Step 1 - push your code to GitHub

See [Publishing to GitHub](#publishing-to-github) below.

### Step 2 - create the web service

1. Sign up at <https://render.com> with your GitHub account.
2. **New** -> **Web Service** -> pick your repository.
3. Fill in:

   | Field | Value |
   | ----- | ----- |
   | Name | `ai-resume-analyzer` |
   | Region | whichever is closest to you |
   | Branch | `main` |
   | Runtime | Python 3 |
   | Build command | `pip install -r requirements.txt` |
   | Start command | `gunicorn wsgi:application --workers 2 --timeout 120 --bind 0.0.0.0:$PORT` |
   | Instance type | Free |

### Step 3 - set the environment variables

In **Environment** -> **Add Environment Variable**:

```
SECRET_KEY        = <your freshly generated key>
FLASK_DEBUG       = False
HOST              = 0.0.0.0
DB_ENABLED        = false
AI_ENABLED        = true
AI_PROVIDER       = gemini
GEMINI_API_KEY    = <your key>
TRUST_PROXY       = true
UPLOAD_RETENTION_HOURS = 1
```

Notes on those last few:

- `TRUST_PROXY=true` because Render sits behind a load balancer, so the real
  visitor IP arrives in `X-Forwarded-For`. Without it, rate limiting would see
  every request as coming from the same address.
- `UPLOAD_RETENTION_HOURS=1` because Render's free disk is temporary anyway,
  and holding strangers' resumes longer than needed is a bad habit.
- Leave `DB_ENABLED=false` unless you have also set up a hosted MySQL
  (see [Adding a database](#adding-a-hosted-database)).

### Step 4 - deploy

Click **Create Web Service**. The first build takes 3-5 minutes. You will get a
URL like `https://ai-resume-analyzer.onrender.com`.

> **Free-tier behaviour.** Render puts a free service to sleep after 15 minutes
> of inactivity, and the next visit takes 30-60 seconds to wake it. Mention this
> if someone tests your link and thinks it is broken.

---

## Option 2: PythonAnywhere (free, good if you want MySQL too)

PythonAnywhere includes a free MySQL database, which Render's free tier does not.

### Step 1 - upload the code

In a **Bash console**:

```bash
git clone https://github.com/YOUR-USERNAME/AI-Resume-Analyzer.git
cd AI-Resume-Analyzer
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2 - create the MySQL database

On the **Databases** tab, set a password and create a database called
`resume_analyzer`. PythonAnywhere prefixes it with your username, so the real
name is something like `yourname$resume_analyzer`.

Load the schema:

```bash
mysql -u yourname -h yourname.mysql.pythonanywhere-services.com \
      -p 'yourname$resume_analyzer' < sql/schema.sql
```

Note that `sql/schema.sql` begins with `CREATE DATABASE` and `USE`. On
PythonAnywhere the database already exists and is named differently, so delete
those first two statements from your copy before running it.

### Step 3 - create the web app

1. **Web** tab -> **Add a new web app** -> **Manual configuration** -> Python 3.10.
2. Set the **Source code** path to `/home/yourname/AI-Resume-Analyzer`.
3. Set the **Virtualenv** path to `/home/yourname/AI-Resume-Analyzer/venv`.
4. Edit the **WSGI configuration file** and replace its contents with:

```python
import sys
import os
from dotenv import load_dotenv

path = "/home/yourname/AI-Resume-Analyzer"
if path not in sys.path:
    sys.path.insert(0, path)

load_dotenv(os.path.join(path, ".env"))

from wsgi import application          # noqa: E402
```

### Step 4 - create `.env` on the server

```bash
cp .env.example .env
nano .env
```

```
SECRET_KEY=<a fresh random value>
FLASK_DEBUG=False
DB_ENABLED=true
DB_HOST=yourname.mysql.pythonanywhere-services.com
DB_USER=yourname
DB_PASSWORD=<your database password>
DB_NAME=yourname$resume_analyzer
```

### Step 5 - reload

Press the green **Reload** button on the Web tab. Your app is live at
`https://yourname.pythonanywhere.com`.

> **Free-tier limit.** PythonAnywhere free accounts can only reach an allow-list
> of external sites. OpenAI and Anthropic are **not** on it, so the AI review
> will fall back to rule-based advice. That is by design and the app handles it
> cleanly - but if you want live AI, use Render instead, or run Ollama locally.

---

## Option 3: A generic Linux server (VPS)

```bash
# 1. Install what you need
sudo apt update && sudo apt install -y python3-venv nginx

# 2. Get the code
git clone https://github.com/YOUR-USERNAME/AI-Resume-Analyzer.git
cd AI-Resume-Analyzer
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env && nano .env      # FLASK_DEBUG=False, real SECRET_KEY

# 4. Run it under systemd so it restarts on boot and on crash
sudo nano /etc/systemd/system/resume-analyzer.service
```

```ini
[Unit]
Description=AI Resume Analyzer
After=network.target

[Service]
User=www-data
WorkingDirectory=/home/youruser/AI-Resume-Analyzer
Environment="PATH=/home/youruser/AI-Resume-Analyzer/venv/bin"
ExecStart=/home/youruser/AI-Resume-Analyzer/venv/bin/gunicorn \
          wsgi:application --workers 3 --timeout 120 --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now resume-analyzer
```

Then put nginx in front of it, so it terminates HTTPS and serves static files:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 6M;          # must exceed our 5 MB upload cap

    location /static/ {
        alias /home/youruser/AI-Resume-Analyzer/static/;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Add free HTTPS with Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

Set `TRUST_PROXY=true` in `.env`, because nginx is now the proxy.

---

## Testing a production setup on Windows

gunicorn does not run on Windows. Use waitress, which is already in
`requirements.txt`:

```powershell
$env:FLASK_DEBUG = "False"
waitress-serve --port=8000 wsgi:application
```

Then open <http://127.0.0.1:8000/>. This is a genuine production server, so it
is a good final check before you deploy.

---

## Adding a hosted database

Render's free tier has no MySQL. Free options that work:

| Service | Free tier |
| ------- | --------- |
| [Railway](https://railway.app) | MySQL with a monthly credit |
| [Aiven](https://aiven.io) | free managed MySQL plan |
| [PlanetScale](https://planetscale.com) | MySQL-compatible |
| PythonAnywhere | MySQL included |

Whichever you pick, set `DB_HOST`, `DB_USER`, `DB_PASSWORD` and `DB_NAME` in
your host's environment settings, then run `sql/schema.sql` against it once.

If you skip this, set `DB_ENABLED=false`. Everything except the History page
works exactly the same.

---

## Publishing to GitHub

### 1. Check nothing secret is about to be committed

```powershell
git status
```

**`.env` must NOT appear in the list.** If it does, stop and check `.gitignore`.

```powershell
git check-ignore -v .env
```

That should print the `.gitignore` rule that excludes it.

### 2. First commit

```powershell
git init
git add .
git commit -m "AI Resume Analyzer: Flask app with ATS scoring, AI review and job matching"
git branch -M main
```

### 3. Create the repository on GitHub

Go to <https://github.com/new>, name it `AI-Resume-Analyzer`, and **do not** tick
"Add a README" - you already have one.

### 4. Push

```powershell
git remote add origin https://github.com/YOUR-USERNAME/AI-Resume-Analyzer.git
git push -u origin main
```

### If you accidentally commit `.env`

Removing the file in a later commit is **not** enough - Git keeps history, and
the key stays readable forever. You must:

1. **Rotate the secret immediately.** Generate a new `SECRET_KEY`, revoke the
   API key at the provider, change the database password. Assume the old ones
   are public.
2. Then clean the history with
   [git-filter-repo](https://github.com/newren/git-filter-repo), or - if the
   repository is new and has no stars or forks - delete it and start again.

Rotating first is the part people skip. Do it first.

---

## Post-deployment checklist

- [ ] `FLASK_DEBUG=False`
- [ ] A fresh `SECRET_KEY`, not the one from your laptop
- [ ] The site loads over **https://**
- [ ] `curl -I https://your-site/` shows `Content-Security-Policy` and
      `X-Frame-Options`
- [ ] An upload works end to end
- [ ] A bad file (a `.txt` renamed to `.pdf`) is rejected cleanly
- [ ] `https://your-site/no-such-page` shows your styled 404, not a stack trace
- [ ] `https://your-site/health` returns `{"status": "ok"}`
- [ ] `TRUST_PROXY=true` if you are behind a proxy or a platform load balancer
- [ ] `.env` is absent from the GitHub repository
- [ ] The live URL is in the repository's **About** section, so visitors find it
