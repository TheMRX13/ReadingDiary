import subprocess
import sys
from werkzeug.middleware.proxy_fix import ProxyFix

# Auto-install fehlende Pakete
def _ensure_packages():
    import importlib
    required = {
        'flask':        'Flask==3.0.3',
        'requests':     'requests==2.31.0',
        'flask_babel':  'Flask-Babel>=4.0.0',
        'flask_limiter':'Flask-Limiter>=3.5.0',
        'flask_wtf':    'Flask-WTF>=1.2.1',
        'argon2':       'argon2-cffi>=23.1.0',
        'dotenv':       'python-dotenv>=1.0.0',
        'pyotp':        'pyotp>=2.9.0',
        'qrcode':       'qrcode[pil]>=7.4.2',
        'apscheduler':  'APScheduler>=3.10.0',
    }
    for module, pkg in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg,
                                   '--break-system-packages'])

_ensure_packages()

# ──────────────────────────────────────────────────────────────────
#  Imports
# ──────────────────────────────────────────────────────────────────
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, Response, make_response, abort, send_from_directory)
from flask_babel import Babel, gettext as _
from flask_limiter import Limiter
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import sqlite3
import os
import re
import secrets
import requests
import json
import csv
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from functools import wraps
import struct
import zlib
import uuid
import zipfile
import shutil
import threading

load_dotenv()

# ──────────────────────────────────────────────────────────────────
#  App & Security Config
# ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_SECURE', '0') == '1'
app.config['WTF_CSRF_SSL_STRICT'] = False
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'
app.config['WTF_CSRF_TIME_LIMIT'] = 3600

SUPPORTED_LANGUAGES = ['de', 'en']
ALLOWED_IPS = [ip.strip() for ip in os.environ.get('ALLOWED_IPS', '127.0.0.1,::1').split(',')]
ENABLE_IP_LOCK = os.environ.get('ENABLE_IP_LOCK', '0') == '1'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reading_diary.db')

csrf = CSRFProtect(app)

def _get_real_ip_for_limiter():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr

limiter = Limiter(
    app=app,
    key_func=_get_real_ip_for_limiter,
    default_limits=[],
    storage_uri="memory://"
)

def get_locale():
    lang = session.get('language', 'de')
    return lang if lang in SUPPORTED_LANGUAGES else 'de'

babel = Babel(app, locale_selector=get_locale)

# Tägliches Backup um 05:00 Uhr
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(create_backup, 'cron', hour=5, minute=0, id='daily_backup', replace_existing=True)
    _scheduler.start()
except Exception as _e:
    app.logger.warning(f'Scheduler nicht gestartet: {_e}')


@app.after_request
def no_cache(response):
    """Verhindert Caching durch Nginx und Browser für HTML-Seiten."""
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Accel-Expires'] = '0'
        response.headers['Surrogate-Control'] = 'no-store'
    # Sicherheits-Header für alle Antworten
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdnjs.cloudflare.com; "
        "connect-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"
    )
    response.headers['Content-Security-Policy'] = csp
    return response


# ──────────────────────────────────────────────────────────────────
#  Sicherheits-Hilfsfunktionen
# ──────────────────────────────────────────────────────────────────
def get_real_ip():
    """Echte Client-IP hinter nginx-Proxy ermitteln."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr


def log_hacker(reason, payload=''):
    """Verdächtigen Request in hacker_logs speichern."""
    ip = get_real_ip()
    ua = (request.headers.get('User-Agent') or '')[:500]
    if not payload:
        try:
            payload = str(request.form.to_dict() or request.get_data(as_text=True)[:500])
        except Exception:
            payload = ''
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO hacker_logs (ip, user_agent, payload, path, reason) VALUES (?,?,?,?,?)",
            (ip, ua, str(payload)[:2000], request.path, reason)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_audit(action, target_uid=None, target_username=None, detail=''):
    """Admin-Aktionen in audit_logs speichern."""
    admin_id = session.get('user_id')
    ip = get_real_ip()
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_logs (admin_id, action, target_user_id, target_username, detail, ip) VALUES (?,?,?,?,?,?)",
            (admin_id, action, target_uid, target_username, detail, ip)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def validate_password_strength(password):
    """Gibt (True, None) oder (False, Fehlermeldung) zurück."""
    if len(password) < 10:
        return False, 'Passwort muss mindestens 10 Zeichen lang sein'
    if not any(c.isupper() for c in password):
        return False, 'Passwort muss mindestens einen Großbuchstaben enthalten'
    if not any(c.islower() for c in password):
        return False, 'Passwort muss mindestens einen Kleinbuchstaben enthalten'
    special = set('!@#$%^&*()_+-=[]{}|;:\'",.<>?/~`\\')
    if not any(c in special for c in password):
        return False, 'Passwort muss mindestens ein Sonderzeichen enthalten (!@#$%^&* ...)'
    return True, None


def hash_pw(password):
    """Passwort mit Argon2 hashen."""
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


def verify_pw(hashed, password):
    """Passwort gegen Argon2-Hash prüfen."""
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
    try:
        return PasswordHasher().verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def send_email(to_addr, subject, html_body, text_body=''):
    """E-Mail versenden. Modus über .env steuerbar:
      SMTP_MODE=ssl       → implizites TLS/SMTPS (Port 465)
      SMTP_MODE=starttls  → STARTTLS (Port 587)
      SMTP_MODE=plain     → kein TLS, plain SMTP (Port 25/1025 etc.)
    Fallback: SMTP_USE_SSL=1 → ssl, SMTP_USE_SSL=0 → starttls (Rückwärtskompatibilität)
    """
    smtp_host = os.environ.get('SMTP_HOST', '')
    smtp_port = int(os.environ.get('SMTP_PORT', 465))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASSWORD', '')
    smtp_from = os.environ.get('SMTP_FROM', smtp_user)

    # Modus bestimmen: SMTP_MODE hat Vorrang, sonst SMTP_USE_SSL als Fallback
    mode = os.environ.get('SMTP_MODE', '').lower()
    if not mode:
        mode = 'ssl' if os.environ.get('SMTP_USE_SSL', '1') == '1' else 'starttls'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = smtp_from
    msg['To']      = to_addr
    if text_body:
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    if mode == 'ssl':
        # Implizites TLS – Verbindung sofort verschlüsselt (typisch Port 465)
        import ssl as _ssl
        ctx = _ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as srv:
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, to_addr, msg.as_string())

    elif mode == 'starttls':
        # STARTTLS – erst plain verbinden, dann auf TLS upgraden (typisch Port 587)
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
            srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, to_addr, msg.as_string())

    else:
        # Plain SMTP – keine Verschlüsselung (für interne/lokale Mailserver)
        with smtplib.SMTP(smtp_host, smtp_port) as srv:
            srv.ehlo()
            if smtp_user:
                srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, to_addr, msg.as_string())

# ──────────────────────────────────────────────────────────────────────────────
#  E-Mail Buddy-Benachrichtigungen
# ──────────────────────────────────────────────────────────────────────────────
def _get_pref(conn, user_id, key):
    """Gibt True zurück wenn Benachrichtigung für key aktiviert ist (Default: an)."""
    row = conn.execute(
        "SELECT enabled FROM notification_prefs WHERE user_id=? AND pref_key=?",
        (user_id, key)
    ).fetchone()
    return (row['enabled'] == 1) if row else True

def notify_buddy_request(to_user_id, from_username, book_title):
    """Sendet E-Mail bei neuer Buddy-Read-Einladung."""
    conn = get_db()
    if not _get_pref(conn, to_user_id, 'buddy_request'):
        conn.close(); return
    user = conn.execute("SELECT email, username FROM users WHERE id=?", (to_user_id,)).fetchone()
    conn.close()
    if not user or not user['email']:
        return
    subject_de = f"📚 Neue Buddy-Read-Einladung von {from_username}"
    subject_en = f"📚 New buddy read invitation from {from_username}"
    html = f"""<div style="font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;border-radius:12px;max-width:500px;">
  <h2 style="color:#3b82f6;">📚 Reading Diary</h2>
  <p>Hey <strong>{user['username']}</strong>,</p>
  <p><strong>{from_username}</strong> lädt dich zu einem gemeinsamen Buddy-Read ein:</p>
  <div style="background:#1e293b;border-radius:8px;padding:1rem;margin:1rem 0;border-left:4px solid #3b82f6;">
    <strong style="color:#f1f5f9;">📖 {book_title}</strong>
  </div>
  <a href="/buddies" style="display:inline-block;background:#3b82f6;color:#fff;padding:.6rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600;">Einladung ansehen</a>
  <p style="color:#64748b;font-size:.8rem;margin-top:1.5rem;">Reading Diary – Du kannst E-Mail-Benachrichtigungen in deinen Einstellungen deaktivieren.</p>
</div>"""
    try:
        send_email(user['email'], subject_de, html)
    except Exception:
        pass

def notify_buddy_accepted(to_user_id, from_username, book_title):
    """Sendet E-Mail wenn Buddy-Read-Einladung angenommen wurde."""
    conn = get_db()
    if not _get_pref(conn, to_user_id, 'buddy_request'):
        conn.close(); return
    user = conn.execute("SELECT email, username FROM users WHERE id=?", (to_user_id,)).fetchone()
    conn.close()
    if not user or not user['email']:
        return
    html = f"""<div style="font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;border-radius:12px;max-width:500px;">
  <h2 style="color:#3b82f6;">📚 Reading Diary</h2>
  <p>Hey <strong>{user['username']}</strong>,</p>
  <p><strong>{from_username}</strong> hat deine Buddy-Read-Einladung <span style="color:#22c55e;font-weight:700;">angenommen</span>!</p>
  <div style="background:#1e293b;border-radius:8px;padding:1rem;margin:1rem 0;border-left:4px solid #22c55e;">
    <strong style="color:#f1f5f9;">📖 {book_title}</strong>
  </div>
  <a href="/buddies" style="display:inline-block;background:#22c55e;color:#fff;padding:.6rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600;">Buddy-Read starten</a>
  <p style="color:#64748b;font-size:.8rem;margin-top:1.5rem;">Reading Diary – Du kannst E-Mail-Benachrichtigungen in deinen Einstellungen deaktivieren.</p>
</div>"""
    try:
        send_email(user['email'], f"✅ {from_username} hat deinen Buddy-Read angenommen – {book_title}", html)
    except Exception:
        pass

def notify_buddy_milestone(to_user_id, from_username, book_title, description):
    """Sendet E-Mail wenn Buddy einen Meilenstein erreicht hat."""
    conn = get_db()
    if not _get_pref(conn, to_user_id, 'buddy_milestone'):
        conn.close(); return
    user = conn.execute("SELECT email, username FROM users WHERE id=?", (to_user_id,)).fetchone()
    conn.close()
    if not user or not user['email']:
        return
    html = f"""<div style="font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;border-radius:12px;max-width:500px;">
  <h2 style="color:#3b82f6;">📚 Reading Diary</h2>
  <p>Hey <strong>{user['username']}</strong>,</p>
  <p><strong>{from_username}</strong> hat einen Meilenstein im Buddy-Read erreicht:</p>
  <div style="background:#1e293b;border-radius:8px;padding:1rem;margin:1rem 0;border-left:4px solid #f59e0b;">
    <div style="color:#f59e0b;font-weight:700;">🏁 {description}</div>
    <div style="color:#94a3b8;font-size:.85rem;margin-top:.3rem;">📖 {book_title}</div>
  </div>
  <a href="/buddies" style="display:inline-block;background:#f59e0b;color:#fff;padding:.6rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600;">Zum Buddy-Read</a>
  <p style="color:#64748b;font-size:.8rem;margin-top:1.5rem;">Reading Diary – Du kannst E-Mail-Benachrichtigungen in deinen Einstellungen deaktivieren.</p>
</div>"""
    try:
        send_email(user['email'], f"🏁 Meilenstein erreicht: {description}", html)
    except Exception:
        pass

def notify_buddy_finished(to_user_id, from_username, book_title):
    """Sendet E-Mail wenn Buddy das Buch fertig gelesen hat."""
    conn = get_db()
    if not _get_pref(conn, to_user_id, 'buddy_milestone'):
        conn.close(); return
    user = conn.execute("SELECT email, username FROM users WHERE id=?", (to_user_id,)).fetchone()
    conn.close()
    if not user or not user['email']:
        return
    html = f"""<div style="font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;border-radius:12px;max-width:500px;">
  <h2 style="color:#3b82f6;">📚 Reading Diary</h2>
  <p>Hey <strong>{user['username']}</strong>,</p>
  <p><strong>{from_username}</strong> hat das Buch fertig gelesen!</p>
  <div style="background:#1e293b;border-radius:8px;padding:1rem;margin:1rem 0;border-left:4px solid #818cf8;">
    <strong style="color:#f1f5f9;">📖 {book_title}</strong>
  </div>
  <p style="color:#94a3b8;">Hol auf! Der Buddy-Read ist beendet.</p>
  <a href="/buddies" style="display:inline-block;background:#818cf8;color:#fff;padding:.6rem 1.4rem;border-radius:8px;text-decoration:none;font-weight:600;">Ergebnis ansehen</a>
  <p style="color:#64748b;font-size:.8rem;margin-top:1.5rem;">Reading Diary – Du kannst E-Mail-Benachrichtigungen in deinen Einstellungen deaktivieren.</p>
</div>"""
    try:
        send_email(user['email'], f"🎉 {from_username} hat '{book_title}' fertiggelesen!", html)
    except Exception:
        pass


def get_app_setting(key, default=''):
    """Liest eine Anwendungseinstellung."""
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row['value'] if row else default
    except Exception:
        return default


def set_app_setting(key, value):
    """Setzt eine Anwendungseinstellung."""
    try:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", (key, str(value)))
        conn.commit()
        conn.close()
    except Exception:
        pass


def create_backup():
    """Erstellt ein ZIP-Backup der Datenbank und Uploads."""
    backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_path = os.path.join(backup_dir, f'backup_{ts}.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(DB_PATH, 'reading_diary.db')
        uploads = os.path.join(os.path.dirname(DB_PATH), 'static', 'uploads')
        if os.path.exists(uploads):
            for root, dirs, files in os.walk(uploads):
                for f in files:
                    fp = os.path.join(root, f)
                    zf.write(fp, os.path.relpath(fp, os.path.dirname(DB_PATH)))
    set_app_setting('last_backup', datetime.now().isoformat())
    # Alte Backups aufräumen (nur letzte 7 behalten)
    all_zips = sorted([f for f in os.listdir(backup_dir) if f.endswith('.zip')])
    for old in all_zips[:-7]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except Exception:
            pass
    return zip_path


# ──────────────────────────────────────────────────────────────────
#  IP-Lock (nur Anfragen vom nginx-Proxy erlauben)
# ──────────────────────────────────────────────────────────────────
@app.before_request
def ip_guard():
    if not ENABLE_IP_LOCK:
        return
    # Localhost immer erlauben (lokales Testen)
    if request.remote_addr in ('127.0.0.1', '::1'):
        return
    if request.path.startswith('/static/'):
        return
    if not request.headers.get('X-Forwarded-For'):
        log_hacker('IP-Lock: Zugriff ohne Proxy-Header versucht')
        abort(403)


@app.before_request
def update_last_seen():
    """Aktualisiert last_seen für eingeloggte User (max. alle 60s per Cookie-Check)."""
    uid = session.get('user_id')
    if uid and not request.path.startswith('/static'):
        # Nur alle 60 Sekunden schreiben um DB-Last zu reduzieren
        ts = session.get('_ls_written', 0)
        import time
        now = int(time.time())
        if now - ts > 60:
            try:
                conn = get_db()
                conn.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE id=?", (uid,))
                conn.commit(); conn.close()
            except Exception:
                pass
            session['_ls_written'] = now

@app.before_request
def check_maintenance():
    """Prüft Wartungsmodus. Admins, statische Dateien und Maintenance-Seite sind erreichbar."""
    if request.path.startswith('/static'):
        return
    if request.path in ('/set-lang/de', '/set-lang/en'):
        return
    # Maintenance-Seite: wenn Modus aus ist, weiterleiten
    if request.path == '/maintenance':
        if get_app_setting('maintenance_mode') != '1':
            return redirect(url_for('login') if not session.get('user_id') else url_for('dashboard'))
        return
    if session.get('is_admin'):
        return
    if get_app_setting('maintenance_mode') == '1':
        if request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Wartungsmodus aktiv'}), 503
        return redirect(url_for('maintenance_page'))


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  DB helpers
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_setting(conn, key, default=''):
    """Liest aus der alten globalen settings-Tabelle (Rückwärtskompatibilität)."""
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else default


def get_user_setting(conn, user_id, key, default=''):
    """Liest eine benutzerspezifische Einstellung."""
    row = conn.execute(
        "SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    return row['value'] if row else default


def upsert_user_setting(conn, user_id, key, value):
    """Speichert eine benutzerspezifische Einstellung."""
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?,?,?)",
        (user_id, key, str(value))
    )


def get_user_setting_direct(user_id, key, default=''):
    """Liest user_setting ohne bestehende Verbindung (öffnet eigene)."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM user_settings WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    conn.close()
    return row['value'] if row else default


def upsert_author(conn, name, user_id):
    if not name or not name.strip():
        return None
    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO authors (name, user_id) VALUES (?,?)", (name, user_id))
    row = conn.execute("SELECT id FROM authors WHERE name=? AND user_id=?", (name, user_id)).fetchone()
    return row['id'] if row else None


def upsert_publisher(conn, name, user_id):
    if not name or not name.strip():
        return None
    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO publishers (name, user_id) VALUES (?,?)", (name, user_id))
    row = conn.execute("SELECT id FROM publishers WHERE name=? AND user_id=?", (name, user_id)).fetchone()
    return row['id'] if row else None


def get_active_goal(conn, user_id):
    row = conn.execute(
        "SELECT * FROM reading_goals WHERE user_id=? AND enabled=1 ORDER BY id DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    return dict(row) if row else None


def goal_progress(conn, goal, user_id):
    if not goal:
        return None
    now = datetime.now(timezone.utc)
    if goal['period'] == 'weekly':
        start = now - timedelta(days=now.weekday())
    elif goal['period'] == 'monthly':
        start = now.replace(day=1)
    else:
        start = now.replace(month=1, day=1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)

    if goal['goal_type'] == 'pages':
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN rp.delta>0 THEN rp.delta ELSE 0 END),0) as total "
            "FROM reading_progress rp "
            "JOIN books b ON b.id=rp.book_id "
            "WHERE b.user_id=? AND rp.timestamp >= ?",
            (user_id, start.isoformat())
        ).fetchone()
        current = row['total']
    else:
        row = conn.execute(
            "SELECT COUNT(*) as total FROM books "
            "WHERE user_id=? AND status='Gelesen' AND read_date >= ?",
            (user_id, start.isoformat())
        ).fetchone()
        current = row['total']

    target = goal['target']
    return {
        'current': current,
        'target': target,
        'percent': min(100, int(current / target * 100)) if target > 0 else 0,
        'type': goal['goal_type'],
        'period': goal['period'],
    }


def reading_streak(conn, user_id):
    """Aktuelle Lesesträhne für einen User."""
    rows = conn.execute(
        "SELECT DISTINCT DATE(ts) as d FROM ("
        "  SELECT rp.timestamp as ts FROM reading_progress rp "
        "  JOIN books b ON b.id=rp.book_id WHERE b.user_id=?"
        "  UNION"
        "  SELECT ap.timestamp as ts FROM audio_progress ap "
        "  JOIN books b ON b.id=ap.book_id WHERE b.user_id=?"
        ") ORDER BY d DESC",
        (user_id, user_id)
    ).fetchall()
    if not rows:
        return 0
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    first = datetime.strptime(rows[0]['d'], '%Y-%m-%d').date()
    if first != today and first != yesterday:
        return 0
    streak = 0
    expected = first
    for row in rows:
        d = datetime.strptime(row['d'], '%Y-%m-%d').date()
        if d == expected:
            streak += 1
            expected -= timedelta(days=1)
        else:
            break
    return streak


def max_reading_streak(conn, user_id):
    """Höchste jemals erreichte Lesesträhne für einen User."""
    rows = conn.execute(
        "SELECT DISTINCT DATE(ts) as d FROM ("
        "  SELECT rp.timestamp as ts FROM reading_progress rp "
        "  JOIN books b ON b.id=rp.book_id WHERE b.user_id=?"
        "  UNION"
        "  SELECT ap.timestamp as ts FROM audio_progress ap "
        "  JOIN books b ON b.id=ap.book_id WHERE b.user_id=?"
        ") ORDER BY d ASC",
        (user_id, user_id)
    ).fetchall()
    if not rows:
        return 0
    max_streak = 1
    current = 1
    for i in range(1, len(rows)):
        prev = datetime.strptime(rows[i-1]['d'], '%Y-%m-%d').date()
        curr = datetime.strptime(rows[i]['d'], '%Y-%m-%d').date()
        if (curr - prev).days == 1:
            current += 1
            if current > max_streak:
                max_streak = current
        else:
            current = 1
    return max_streak


@app.template_filter('trstatus')
def translate_status(status):
    """Translates DB status value (always German) to current UI language."""
    return {
        'Ungelesen': _('Unread'),
        'Am Lesen':  _('Reading'),
        'Gelesen':   _('Read'),
        'Am H\u00f6ren': _('Listening'),
    }.get(status, status)


@app.template_filter('trperiod')
def translate_period(period):
    return {
        'weekly':  _('Weekly'),
        'monthly': _('Monthly'),
        'yearly':  _('Yearly'),
    }.get(period, period)


@app.template_filter('trgoaltype')
def translate_goal_type(goal_type):
    return {
        'pages': _('Pages'),
        'books': _('Books'),
    }.get(goal_type, goal_type)


@app.template_filter('fmtdate')
def format_date(value):
    """Konvertiert yyyy-mm-dd zu dd.mm.yyyy für die Anzeige."""
    if not value:
        return value
    s = str(value).strip()
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s[8:10] + '.' + s[5:7] + '.' + s[0:4]
    return s


# ──────────────────────────────────────────────────────────────────
#  Auth
# ──────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return deco


def admin_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if not session.get('is_admin'):
            abort(403)
        return f(*args, **kwargs)
    return deco


@app.context_processor
def inject_globals():
    uid = session.get('user_id')
    if not uid:
        return {}
    try:
        conn = get_db()
        def gs(key, default=''):
            return get_user_setting(conn, uid, key, default)
        dark_mode      = gs('dark_mode',      'false') == 'true'
        show_reviews   = gs('show_reviews',   'true')  == 'true'
        show_stars     = gs('show_stars',     'true')  == 'true'
        show_spice     = gs('show_spice',     'true')  == 'true'
        show_tension   = gs('show_tension',   'true')  == 'true'
        show_fiction   = gs('show_fiction',   'true')  == 'true'
        show_lent      = gs('show_lent',      'true')  == 'true'
        show_streak    = gs('show_streak',    'true')  == 'true'
        show_audiobook = gs('show_audiobook', 'true')  == 'true'
        language = gs('language', 'de')
        if session.get('language') != language:
            session['language'] = language
        goal     = get_active_goal(conn, uid)
        progress = goal_progress(conn, goal, uid)
        streak   = reading_streak(conn, uid)
        # Aktive Werbebanner für alle User laden
        active_ads = conn.execute(
            "SELECT a.*, u.username FROM advertisements a "
            "JOIN users u ON u.id=a.user_id WHERE a.is_active=1"
        ).fetchall()
        conn.close()
        return {
            'dark_mode':        dark_mode,
            'show_reviews':     show_reviews,
            'show_stars':       show_stars,
            'show_spice':       show_spice,
            'show_tension':     show_tension,
            'show_fiction':     show_fiction,
            'show_lent':        show_lent,
            'show_streak':      show_streak,
            'show_audiobook':   show_audiobook,
            'current_language': language,
            'goal':             goal,
            'goal_progress':    progress,
            'streak':           streak,
            'current_user_id':  uid,
            'current_username': session.get('username', ''),
            'is_admin':         bool(session.get('is_admin', False)),
            'active_ads':       active_ads,
        }
    except Exception:
        return {}


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  Page routes
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

# ── Pretty-URL: .html-Suffix → 301 Redirect ──────────────────────────────────
@app.route('/<path:path>.html')
def strip_html_extension(path):
    """Leitet alte .html-URLs permanent auf die saubere Version weiter."""
    clean = '/' + path
    qs = request.query_string.decode()
    if qs:
        clean += '?' + qs
    return redirect(clean, 301)


@app.route('/')
def index():
    from datetime import datetime as _dt
    logged_in = bool(session.get('user_id'))
    return render_template('landing.html', year=_dt.now().year, logged_in=logged_in)


# ── Login ─────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per 5 minutes", methods=["POST"])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password   = request.form.get('password', '')
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE (username=? OR email=?) AND is_banned=0",
            (identifier, identifier.lower())
        ).fetchone()
        conn.close()
        if not user or not verify_pw(user['password_hash'], password):
            log_hacker('Fehlgeschlagener Login', f'identifier={identifier[:50]}')
            error = 'Ungültige Anmeldedaten.'
        elif not user['email_verified']:
            error = 'Bitte bestätige zuerst deine E-Mail-Adresse.'
        elif not user['is_active']:
            error = 'Dein Account wartet auf Admin-Freigabe.'
        else:
            if user['totp_enabled']:
                session['pending_2fa_user'] = user['id']
                return redirect(url_for('two_factor'))
            session.permanent = True
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            lang = get_user_setting_direct(user['id'], 'language', 'de')
            session['language'] = lang
            # IP-Login speichern
            try:
                ip = get_real_ip()
                conn2 = get_db()
                conn2.execute("INSERT INTO user_ips (user_id, ip) VALUES (?,?)", (user['id'], ip))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
            return redirect(url_for('dashboard'))
    return render_template('login.html', error=error)


# ── Öffentlicher Sprachumschalter (kein Login nötig) ─────────────
@app.route('/set-lang/<lang>')
def set_lang_public(lang):
    """Sprache für Login/Register-Seiten setzen, ohne eingeloggt zu sein."""
    if lang in SUPPORTED_LANGUAGES:
        session['language'] = lang
    return redirect(request.referrer or url_for('login'))


# ── Logout ────────────────────────────────────────────────────────
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index') + '?bye=1')


# ── Registrierung ─────────────────────────────────────────────────
@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=["POST"])
def register():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    errors = []
    if request.method == 'POST':
        # Honeypot-Prüfung (Bots füllen dieses versteckte Feld aus)
        if request.form.get('website', ''):
            log_hacker('Honeypot bei Registrierung ausgelöst')
            return render_template('register.html', errors=['Registrierung fehlgeschlagen.'])

        username       = request.form.get('username', '').strip()
        email          = request.form.get('email', '').strip().lower()
        password       = request.form.get('password', '')
        password2      = request.form.get('password2', '')
        accept_privacy = request.form.get('accept_privacy', '')

        # Input-Validierung
        if not accept_privacy:
            errors.append('Bitte akzeptiere die Datenschutzerklärung.')
        if not re.match(r'^[a-zA-Z0-9_]{3,50}$', username):
            errors.append('Benutzername: 3–50 Zeichen, nur Buchstaben, Zahlen und _')
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            errors.append('Ungültige E-Mail-Adresse')
        if password != password2:
            errors.append('Passwörter stimmen nicht überein')
        else:
            ok, msg = validate_password_strength(password)
            if not ok:
                errors.append(msg)

        if not errors:
            conn = get_db()
            existing = conn.execute(
                "SELECT id FROM users WHERE username=? OR email=?", (username, email)
            ).fetchone()
            if existing:
                conn.close()
                errors.append('Benutzername oder E-Mail bereits vergeben')
            else:
                pw_hash = hash_pw(password)
                token   = secrets.token_urlsafe(48)
                expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
                conn.execute(
                    "INSERT INTO users (username, email, password_hash, verification_token, "
                    "token_expires_at, is_active, email_verified) VALUES (?,?,?,?,?,0,0)",
                    (username, email, pw_hash, token, expires)
                )
                conn.commit()
                conn.close()
                base_url = os.environ.get('APP_BASE_URL', 'http://localhost:5000')
                verify_url = f"{base_url}/verify-email/{token}"
                try:
                    send_email(
                        email,
                        'E-Mail bestätigen – Reading Diary',
                        f'<h2>Willkommen, {username}!</h2>'
                        f'<p>Bitte bestätige deine E-Mail-Adresse:</p>'
                        f'<p><a href="{verify_url}" style="background:#3b82f6;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;">E-Mail bestätigen</a></p>'
                        f'<p>Oder kopiere diesen Link: {verify_url}</p>'
                        f'<p><small>Link gültig für 24 Stunden.</small></p>',
                        f'Bitte bestätige deine E-Mail: {verify_url}'
                    )
                except Exception as e:
                    app.logger.error(f'E-Mail-Versand fehlgeschlagen: {e}')
                return render_template('register_success.html', email=email)

    return render_template('register.html', errors=errors)


# ── E-Mail-Bestätigung ────────────────────────────────────────────
@app.route('/verify-email/<token>')
def verify_email(token):
    # Path-Traversal-Schutz
    if not re.match(r'^[A-Za-z0-9_\-]{20,100}$', token):
        abort(400)
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE verification_token=?", (token,)
    ).fetchone()
    if not user:
        conn.close()
        return render_template('verify_result.html', success=False,
                               message='Ungültiger oder bereits verwendeter Link.')
    expires = user['token_expires_at']
    if expires:
        exp_dt = datetime.fromisoformat(expires)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            conn.close()
            return render_template('verify_result.html', success=False,
                                   message='Der Bestätigungslink ist abgelaufen. Bitte neu registrieren.')
    conn.execute(
        "UPDATE users SET email_verified=1, is_active=1, verification_token=NULL, token_expires_at=NULL WHERE id=?",
        (user['id'],)
    )
    conn.commit()
    conn.close()
    return render_template('verify_result.html', success=True,
                           message='E-Mail erfolgreich bestätigt! Dein Account ist jetzt aktiviert.')


# ── Impressum und Datenschutz ─────────────────────────────────────
@app.route('/impressum')
def impressum():
    """Impressum - öffentliche Seite ohne Login erforderlich."""
    return render_template('impressum.html')


@app.route('/datenschutz')
def datenschutz():
    """Datenschutzerklärung - öffentliche Seite ohne Login erforderlich."""
    return render_template('datenschutz.html')


# ── Passwort vergessen ────────────────────────────────────────────
@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=["POST"])
def forgot_password():
    """Passwort-Reset anfordern."""
    if session.get('user_id'):
        return redirect(url_for('dashboard'))

    success = False
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
            (identifier, identifier.lower())
        ).fetchone()

        if user:
            # Token generieren und in DB speichern
            reset_token = secrets.token_urlsafe(48)
            expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            conn.execute(
                "UPDATE users SET reset_token=?, reset_token_expires_at=? WHERE id=?",
                (reset_token, expires, user['id'])
            )
            conn.commit()

            base_url = os.environ.get('APP_BASE_URL', 'http://localhost:5000')
            reset_url = f"{base_url}/reset-password/{reset_token}"
            try:
                send_email(
                    user['email'],
                    'Passwort zurücksetzen – Reading Diary',
                    f'<h2>Passwort-Reset</h2>'
                    f'<p>Hallo {user["username"]},</p>'
                    f'<p>Klicke auf den Button unten, um dein Passwort zurückzusetzen:</p>'
                    f'<p><a href="{reset_url}" style="background:#3b82f6;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;">Passwort zurücksetzen</a></p>'
                    f'<p>Oder kopiere diesen Link: {reset_url}</p>'
                    f'<p><small>Link gültig für 2 Stunden. Falls du diesen Link nicht angefordert hast, ignoriere diese E-Mail.</small></p>',
                    f'Passwort-Reset: {reset_url}'
                )
            except Exception as e:
                app.logger.error(f'Reset-E-Mail-Versand fehlgeschlagen: {e}')

        conn.close()
        success = True

    return render_template('forgot_password.html', success=success)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def reset_password(token):
    """Passwort mit Token zurücksetzen."""
    if session.get('user_id'):
        return redirect(url_for('dashboard'))

    # Path-Traversal-Schutz
    if not re.match(r'^[A-Za-z0-9_\-]{20,100}$', token):
        abort(400)

    error = None
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE reset_token=?", (token,)
    ).fetchone()

    if not user:
        conn.close()
        return render_template('reset_password.html', success=False,
                              error='Ungültiger oder bereits verwendeter Link.')

    # Token-Ablauf prüfen
    if user['reset_token_expires_at']:
        exp_dt = datetime.fromisoformat(user['reset_token_expires_at'])
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            conn.close()
            return render_template('reset_password.html', success=False,
                                  error='Der Reset-Link ist abgelaufen.')

    if request.method == 'POST':
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')

        if password != password2:
            error = 'Passwörter stimmen nicht überein'
        else:
            ok, msg = validate_password_strength(password)
            if not ok:
                error = msg

        if not error:
            pw_hash = hash_pw(password)
            conn.execute(
                "UPDATE users SET password_hash=?, reset_token=NULL, reset_token_expires_at=NULL WHERE id=?",
                (pw_hash, user['id'])
            )
            conn.commit()
            conn.close()
            return render_template('reset_password.html', success=True)

    conn.close()
    return render_template('reset_password.html', error=error)


@csrf.exempt
@app.route('/admin/users/<int:uid>/send-reset', methods=['POST'])
@login_required
@admin_required
def admin_send_reset(uid):
    """Admin sendet Reset-Link an Benutzer."""
    if not session.get('is_admin'):
        return jsonify({'error': 'Nur für Admins'}), 403

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    if not user:
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404

    reset_token = secrets.token_urlsafe(48)
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    conn.execute(
        "UPDATE users SET reset_token=?, reset_token_expires_at=? WHERE id=?",
        (reset_token, expires, uid)
    )
    conn.commit()
    conn.close()

    base_url = os.environ.get('APP_BASE_URL', 'http://localhost:5000')
    reset_url = f"{base_url}/reset-password/{reset_token}"

    try:
        send_email(
            user['email'],
            'Passwort zurücksetzen – Reading Diary',
            f'<h2>Passwort-Reset</h2>'
            f'<p>Hallo {user["username"]},</p>'
            f'<p>Klicke auf den Button unten, um dein Passwort zurückzusetzen:</p>'
            f'<p><a href="{reset_url}" style="background:#3b82f6;color:#fff;padding:10px 20px;text-decoration:none;border-radius:6px;">Passwort zurücksetzen</a></p>'
            f'<p>Oder kopiere diesen Link: {reset_url}</p>'
            f'<p><small>Link gültig für 2 Stunden.</small></p>',
            f'Passwort-Reset: {reset_url}'
        )
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f'Reset-E-Mail-Versand fehlgeschlagen: {e}')
        return jsonify({'error': 'E-Mail-Versand fehlgeschlagen'}), 500


# ── 2FA ───────────────────────────────────────────────────────────
@app.route('/2fa', methods=['GET', 'POST'])
@limiter.limit("10 per 5 minutes", methods=["POST"])
def two_factor():
    uid = session.get('pending_2fa_user')
    if not uid:
        return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        if user and user['totp_secret']:
            import pyotp
            if pyotp.TOTP(user['totp_secret']).verify(code):
                session.pop('pending_2fa_user', None)
                session.permanent  = True
                session['user_id']  = user['id']
                session['username'] = user['username']
                session['is_admin'] = bool(user['is_admin'])
                return redirect(url_for('dashboard'))
        log_hacker('Fehlgeschlagener 2FA-Versuch')
        error = 'Ungültiger Code'
    return render_template('two_factor.html', error=error)


@csrf.exempt
@app.route('/api/2fa/setup', methods=['POST'])
@login_required
def setup_2fa():
    import pyotp, qrcode as _qrcode, base64
    uid = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    secret = pyotp.random_base32()
    conn.execute("UPDATE users SET totp_secret=? WHERE id=?", (secret, uid))
    conn.commit()
    conn.close()
    uri = pyotp.TOTP(secret).provisioning_uri(user['username'], issuer_name='Reading Diary')
    img = _qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return jsonify({'secret': secret, 'qr': f'data:image/png;base64,{qr_b64}'})


@csrf.exempt
@app.route('/api/2fa/confirm', methods=['POST'])
@login_required
def confirm_2fa():
    import pyotp
    code = (request.json or {}).get('code', '')
    uid  = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT totp_secret FROM users WHERE id=?", (uid,)).fetchone()
    if user and user['totp_secret'] and pyotp.TOTP(user['totp_secret']).verify(code):
        conn.execute("UPDATE users SET totp_enabled=1 WHERE id=?", (uid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    conn.close()
    return jsonify({'error': 'Ungültiger Code'}), 400


@csrf.exempt
@app.route('/api/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    uid = session['user_id']
    conn = get_db()
    conn.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/dashboard')
@login_required
def dashboard():
    uid = session['user_id']
    conn = get_db()
    total_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=?", (uid,)).fetchone()['c']
    read_books  = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Gelesen'", (uid,)).fetchone()['c']
    total_quotes = conn.execute(
        "SELECT COUNT(*) as c FROM quotes q JOIN books b ON b.id=q.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()['c']
    reading = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? AND b.status='Am Lesen' ORDER BY b.added_date DESC",
        (uid,)
    ).fetchall()
    recent = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? AND b.status != 'Am Lesen' ORDER BY b.added_date DESC LIMIT 8",
        (uid,)
    ).fetchall()
    conn.close()
    resp = make_response(render_template('dashboard.html',
                           total_books=total_books,
                           read_books=read_books,
                           total_quotes=total_quotes,
                           reading=reading,
                           recent=recent))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/books')
@login_required
def books():
    uid = session['user_id']
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        books_list = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id "
            "WHERE b.user_id=? AND (b.title LIKE ? OR a.name LIKE ? OR b.isbn LIKE ?) "
            "ORDER BY b.added_date DESC",
            (uid, f'%{q}%', f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        books_list = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id "
            "WHERE b.user_id=? ORDER BY b.added_date DESC",
            (uid,)
        ).fetchall()
    all_series  = conn.execute("SELECT * FROM series WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    all_shelves = conn.execute("SELECT * FROM shelves WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    conn.close()
    return render_template('books.html', books=books_list, q=q,
                           all_series=all_series, all_shelves=all_shelves)


@app.route('/books/<int:book_id>')
@login_required
def book_detail(book_id):
    uid = session['user_id']
    conn = get_db()
    book = conn.execute(
        "SELECT b.*, a.name as author_name, p.name as publisher_name, "
        "s.name as series_group_name "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id "
        "LEFT JOIN series s ON s.id=b.series_id "
        "WHERE b.id=? AND b.user_id=?",
        (book_id, uid)
    ).fetchone()
    if not book:
        conn.close()
        return redirect(url_for('books'))

    progress_history = conn.execute(
        "SELECT * FROM reading_progress WHERE book_id=? ORDER BY timestamp DESC LIMIT 50",
        (book_id,)
    ).fetchall()
    current_page = progress_history[0]['page'] if progress_history else 0

    audio_history = conn.execute(
        "SELECT * FROM audio_progress WHERE book_id=? ORDER BY timestamp DESC LIMIT 50",
        (book_id,)
    ).fetchall()
    current_percent = audio_history[0]['percent'] if audio_history else 0

    rating   = conn.execute("SELECT * FROM ratings WHERE book_id=?", (book_id,)).fetchone()
    review   = conn.execute("SELECT * FROM reviews WHERE book_id=?", (book_id,)).fetchone()
    notes    = conn.execute(
        "SELECT * FROM book_notes WHERE book_id=? ORDER BY created_at ASC", (book_id,)
    ).fetchall()
    all_series   = conn.execute("SELECT * FROM series WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    show_reviews = get_user_setting(conn, uid, 'show_reviews', 'true') == 'true'
    conn.close()

    from_series = request.args.get('from_series', type=int)
    return render_template('book_detail.html',
                           book=book,
                           progress_history=progress_history,
                           current_page=current_page,
                           audio_history=audio_history,
                           current_percent=current_percent,
                           rating=rating,
                           review=review,
                           notes=notes,
                           all_series=all_series,
                           show_reviews=show_reviews,
                           from_series=from_series)


@app.route('/wishlist')
@login_required
def wishlist():
    uid = session['user_id']
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        items = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id "
            "WHERE w.user_id=? AND (w.title LIKE ? OR a.name LIKE ?) ORDER BY w.added_date DESC",
            (uid, f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        items = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id "
            "WHERE w.user_id=? ORDER BY w.added_date DESC",
            (uid,)
        ).fetchall()
    conn.close()
    return render_template('wishlist.html', items=items, q=q)


@app.route('/quotes')
@login_required
def quotes():
    uid = session['user_id']
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        quotes_list = conn.execute(
            "SELECT qt.*, b.title as book_title, a.name as author_name "
            "FROM quotes qt JOIN books b ON qt.book_id=b.id "
            "LEFT JOIN authors a ON b.author_id=a.id "
            "WHERE b.user_id=? AND (qt.quote_text LIKE ? OR b.title LIKE ?) ORDER BY qt.added_date DESC",
            (uid, f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        quotes_list = conn.execute(
            "SELECT qt.*, b.title as book_title, a.name as author_name "
            "FROM quotes qt JOIN books b ON qt.book_id=b.id "
            "LEFT JOIN authors a ON b.author_id=a.id "
            "WHERE b.user_id=? ORDER BY qt.added_date DESC",
            (uid,)
        ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id WHERE b.user_id=? ORDER BY b.title",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template('quotes.html', quotes=quotes_list, books=all_books, q=q)


@app.route('/statistics')
@login_required
def statistics():
    uid = session['user_id']
    conn = get_db()
    skeys = ['show_stats_total', 'show_stats_publishers', 'show_stats_authors', 'show_stats_graphs']
    stats_settings = {k: get_user_setting(conn, uid, k, 'true') == 'true' for k in skeys}

    now_year = datetime.now(timezone.utc).year

    # ── Gesamtzahlen ──
    total_books   = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=?", (uid,)).fetchone()['c']
    read_books    = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Gelesen'", (uid,)).fetchone()['c']
    unread_books  = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Ungelesen'", (uid,)).fetchone()['c']
    reading_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Am Lesen'", (uid,)).fetchone()['c']

    # Gelesene Seiten (nur Nicht-Hörbücher)
    total_pages = conn.execute(
        "SELECT COALESCE((SELECT SUM(CASE WHEN rp.delta>0 THEN rp.delta ELSE 0 END)"
        "                 FROM reading_progress rp"
        "                 JOIN books b ON b.id=rp.book_id WHERE b.user_id=? AND b.is_audiobook=0), 0)"
        " + COALESCE((SELECT SUM(b.pages) FROM books b WHERE b.user_id=? AND b.status='Gelesen'"
        "             AND b.is_audiobook=0 AND COALESCE(b.pages,0)>0"
        "             AND NOT EXISTS (SELECT 1 FROM reading_progress rp WHERE rp.book_id=b.id)), 0) as t",
        (uid, uid)
    ).fetchone()['t']

    total_quotes = conn.execute(
        "SELECT COUNT(*) as c FROM quotes q JOIN books b ON b.id=q.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()['c']

    # ── Hörbuch-Statistiken ──
    audio_total   = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND is_audiobook=1", (uid,)).fetchone()['c']
    audio_read    = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND is_audiobook=1 AND status='Gelesen'", (uid,)).fetchone()['c']
    audio_reading = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND is_audiobook=1 AND status='Am Lesen'", (uid,)).fetchone()['c']
    audio_unread  = conn.execute("SELECT COUNT(*) as c FROM books WHERE user_id=? AND is_audiobook=1 AND status='Ungelesen'", (uid,)).fetchone()['c']

    audio_sessions = conn.execute(
        "SELECT COUNT(*) as c FROM audio_progress ap JOIN books b ON b.id=ap.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()['c']
    audio_this_year = conn.execute(
        "SELECT COUNT(*) as c FROM books WHERE user_id=? AND is_audiobook=1 AND status='Gelesen'"
        " AND strftime('%Y', read_date)=?", (uid, str(now_year))
    ).fetchone()['c']

    # ── Aktivitätstage ──
    reading_days = conn.execute(
        "SELECT COUNT(DISTINCT DATE(rp.timestamp)) as c FROM reading_progress rp "
        "JOIN books b ON b.id=rp.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()['c']
    listening_days = conn.execute(
        "SELECT COUNT(DISTINCT DATE(ap.timestamp)) as c FROM audio_progress ap "
        "JOIN books b ON b.id=ap.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()['c']
    total_active_days = conn.execute(
        "SELECT COUNT(DISTINCT DATE(ts)) as c FROM ("
        "  SELECT rp.timestamp as ts FROM reading_progress rp JOIN books b ON b.id=rp.book_id WHERE b.user_id=?"
        "  UNION ALL"
        "  SELECT ap.timestamp as ts FROM audio_progress ap JOIN books b ON b.id=ap.book_id WHERE b.user_id=?)",
        (uid, uid)
    ).fetchone()['c']

    # ── Lesegeschwindigkeit ──
    rp_stats = conn.execute(
        "SELECT COUNT(DISTINCT DATE(rp.timestamp)) as days,"
        "       COALESCE(SUM(CASE WHEN rp.delta>0 THEN rp.delta ELSE 0 END),0) as pages"
        " FROM reading_progress rp JOIN books b ON b.id=rp.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()
    avg_pages_per_day = round(rp_stats['pages'] / rp_stats['days'], 0) if rp_stats['days'] > 0 else 0

    ap_stats = conn.execute(
        "SELECT COUNT(DISTINCT DATE(ap.timestamp)) as days,"
        "       COALESCE(SUM(CASE WHEN ap.delta>0 THEN ap.delta ELSE 0 END),0) as pct"
        " FROM audio_progress ap JOIN books b ON b.id=ap.book_id WHERE b.user_id=?", (uid,)
    ).fetchone()
    avg_pct_per_listen_day = round(ap_stats['pct'] / ap_stats['days'], 1) if ap_stats['days'] > 0 else 0

    # ── Jahres-/Monatsstats ──
    books_this_year = conn.execute(
        "SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Gelesen'"
        " AND strftime('%Y', read_date)=?", (uid, str(now_year))
    ).fetchone()['c']

    start_12m = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    books_last_12m = conn.execute(
        "SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Gelesen' AND read_date >= ?",
        (uid, start_12m)
    ).fetchone()['c']
    avg_books_per_month = round(books_last_12m / 12, 1)

    # ── Bewertungen & Genre ──
    avg_rating_row = conn.execute(
        "SELECT ROUND(AVG(CAST(r.stars AS FLOAT)), 1) as r FROM ratings r "
        "JOIN books b ON b.id=r.book_id WHERE b.user_id=? AND r.stars > 0", (uid,)
    ).fetchone()
    avg_rating = avg_rating_row['r'] or 0

    fav_genre_row = conn.execute(
        "SELECT genre, COUNT(*) as c FROM books"
        " WHERE user_id=? AND status='Gelesen' AND genre IS NOT NULL AND genre != ''"
        " GROUP BY genre ORDER BY c DESC LIMIT 1", (uid,)
    ).fetchone()
    fav_genre       = fav_genre_row['genre'] if fav_genre_row else '–'
    fav_genre_count = fav_genre_row['c'] if fav_genre_row else 0

    genres_stats = conn.execute(
        "SELECT COALESCE(NULLIF(genre,''), 'Unbekannt') as name, COUNT(*) as cnt"
        " FROM books WHERE user_id=? AND genre IS NOT NULL AND genre != ''"
        " GROUP BY genre ORDER BY cnt DESC LIMIT 10", (uid,)
    ).fetchall()

    formats_stats = conn.execute(
        "SELECT CASE WHEN is_audiobook=1 THEN 'Hörbuch'"
        "            ELSE COALESCE(NULLIF(format,''), 'Unbekannt') END as name,"
        "       COUNT(*) as cnt"
        " FROM books WHERE user_id=? GROUP BY name ORDER BY cnt DESC", (uid,)
    ).fetchall()

    publishers_stats = conn.execute(
        "SELECT p.name, COUNT(b.id) as cnt FROM publishers p "
        "JOIN books b ON b.publisher_id=p.id WHERE b.user_id=? GROUP BY p.id ORDER BY cnt DESC",
        (uid,)
    ).fetchall()
    authors_stats = conn.execute(
        "SELECT a.name, COUNT(b.id) as cnt FROM authors a "
        "JOIN books b ON b.author_id=a.id WHERE b.user_id=? GROUP BY a.id ORDER BY cnt DESC LIMIT 20",
        (uid,)
    ).fetchall()

    goals          = conn.execute("SELECT * FROM reading_goals WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()
    current_streak = reading_streak(conn, uid)
    best_streak    = max_reading_streak(conn, uid)
    conn.close()

    return render_template('statistics.html',
                           stats=stats_settings,
                           now_year=now_year,
                           total_books=total_books,
                           read_books=read_books,
                           unread_books=unread_books,
                           reading_books=reading_books,
                           total_pages=total_pages,
                           total_quotes=total_quotes,
                           audio_total=audio_total,
                           audio_read=audio_read,
                           audio_reading=audio_reading,
                           audio_unread=audio_unread,
                           audio_sessions=audio_sessions,
                           audio_this_year=audio_this_year,
                           reading_days=reading_days,
                           listening_days=listening_days,
                           total_active_days=total_active_days,
                           avg_pages_per_day=int(avg_pages_per_day),
                           avg_pct_per_listen_day=avg_pct_per_listen_day,
                           books_this_year=books_this_year,
                           avg_books_per_month=avg_books_per_month,
                           avg_rating=avg_rating,
                           fav_genre=fav_genre,
                           fav_genre_count=fav_genre_count,
                           genres_stats=genres_stats,
                           formats_stats=formats_stats,
                           publishers_stats=publishers_stats,
                           authors_stats=authors_stats,
                           goals=goals,
                           current_streak=current_streak,
                           best_streak=best_streak)


@app.route('/settings')
@login_required
def settings():
    uid = session['user_id']
    conn = get_db()
    all_s = {}
    for row in conn.execute("SELECT key, value FROM user_settings WHERE user_id=?", (uid,)):
        all_s[row['key']] = row['value']
    defaults = {
        'dark_mode': 'false', 'show_reviews': 'true',
        'show_stats_total': 'true', 'show_stats_publishers': 'true',
        'show_stats_authors': 'true', 'show_stats_graphs': 'true',
        'show_stars': 'true', 'show_spice': 'true',
        'show_tension': 'true', 'show_fiction': 'true',
        'show_lent': 'true', 'show_streak': 'true',
        'show_audiobook': 'true',
    }
    for k, v in defaults.items():
        all_s.setdefault(k, v)

    user        = conn.execute("SELECT ad_enabled, totp_enabled FROM users WHERE id=?", (uid,)).fetchone()
    ad_enabled  = bool(user['ad_enabled']) if user else False
    totp_enabled = bool(user['totp_enabled']) if user else False
    my_ad       = conn.execute("SELECT * FROM advertisements WHERE user_id=?", (uid,)).fetchone() if ad_enabled else None
    active_ads  = conn.execute(
        "SELECT a.*, u.username FROM advertisements a JOIN users u ON u.id=a.user_id WHERE a.is_active=1"
    ).fetchall()

    authors_list    = conn.execute("SELECT * FROM authors WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    publishers_list = conn.execute("SELECT * FROM publishers WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    goals           = conn.execute("SELECT * FROM reading_goals WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall()

    # Support: ungelesene Admin-Antworten zählen
    support_unread = conn.execute("""
        SELECT COUNT(*) as c FROM support_replies sr
        JOIN support_tickets st ON sr.ticket_id=st.id
        WHERE st.user_id=? AND sr.is_admin=1 AND sr.read_at IS NULL
    """, (uid,)).fetchone()['c']

    # Meine Unterhaltungen: Mutuals mit letzter Nachricht
    mutual_chats = conn.execute("""
        SELECT u.id, u.username,
               (SELECT content FROM chat_messages
                WHERE (sender_id=u.id AND receiver_id=?) OR (sender_id=? AND receiver_id=u.id)
                ORDER BY created_at DESC LIMIT 1) as last_msg,
               (SELECT COUNT(*) FROM chat_messages
                WHERE sender_id=u.id AND receiver_id=? AND read_at IS NULL) as unread
        FROM users u
        WHERE u.id IN (SELECT followed_id FROM follows WHERE follower_id=?)
          AND u.id IN (SELECT follower_id FROM follows WHERE followed_id=?)
          AND u.is_active=1
        ORDER BY (SELECT created_at FROM chat_messages
                  WHERE (sender_id=u.id AND receiver_id=?) OR (sender_id=? AND receiver_id=u.id)
                  ORDER BY created_at DESC LIMIT 1) DESC NULLS LAST
        LIMIT 5
    """, (uid, uid, uid, uid, uid, uid, uid)).fetchall()

    conn.close()
    return render_template('settings.html', s=all_s,
                           authors=authors_list,
                           publishers=publishers_list,
                           goals=goals,
                           now_year=datetime.now(timezone.utc).year,
                           ad_enabled=ad_enabled,
                           totp_enabled=totp_enabled,
                           my_ad=my_ad,
                           active_ads=active_ads,
                           support_unread=support_unread,
                           mutual_chats=mutual_chats)


# ── Support-System ────────────────────────────────────────────────
@app.route('/support')
@login_required
def support():
    uid = session['user_id']
    conn = get_db()
    tickets = conn.execute("""
        SELECT st.*,
               (SELECT COUNT(*) FROM support_replies sr
                WHERE sr.ticket_id=st.id AND sr.is_admin=1 AND sr.read_at IS NULL) as unread_replies,
               (SELECT COUNT(*) FROM support_replies WHERE ticket_id=st.id) as reply_count
        FROM support_tickets st
        WHERE st.user_id=?
        ORDER BY st.created_at DESC
    """, (uid,)).fetchall()
    conn.close()
    return render_template('support.html', tickets=tickets)


@app.route('/support/<int:ticket_id>')
@login_required
def support_ticket_view(ticket_id):
    uid = session['user_id']
    conn = get_db()
    ticket = conn.execute(
        "SELECT * FROM support_tickets WHERE id=? AND user_id=?", (ticket_id, uid)
    ).fetchone()
    if not ticket:
        conn.close()
        abort(404)
    replies = conn.execute(
        "SELECT sr.*, u.username FROM support_replies sr "
        "JOIN users u ON sr.sender_id=u.id WHERE sr.ticket_id=? ORDER BY sr.created_at ASC",
        (ticket_id,)
    ).fetchall()
    # Als gelesen markieren
    conn.execute(
        "UPDATE support_replies SET read_at=CURRENT_TIMESTAMP "
        "WHERE ticket_id=? AND is_admin=1 AND read_at IS NULL", (ticket_id,)
    )
    conn.commit()
    conn.close()
    return render_template('support_ticket.html', ticket=ticket, replies=replies)


@csrf.exempt
@app.route('/api/support/ticket', methods=['POST'])
@login_required
def support_create_ticket():
    uid = session['user_id']
    data = request.get_json() or {}
    subject  = (data.get('subject') or '').strip()
    message  = (data.get('message') or '').strip()
    category = data.get('category', 'general')
    if not subject or not message:
        return jsonify({'success': False, 'error': 'Betreff und Nachricht erforderlich'})
    if len(message) > 2000:
        return jsonify({'success': False, 'error': 'Nachricht zu lang (max 2000 Zeichen)'})
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO support_tickets (user_id, subject, message, category) VALUES (?,?,?,?)",
        (uid, subject, message, category)
    )
    ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'ticket_id': ticket_id})


@csrf.exempt
@app.route('/api/support/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
def support_reply(ticket_id):
    uid = session['user_id']
    is_admin = session.get('is_admin', False)
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'Nachricht darf nicht leer sein'})
    conn = get_db()
    ticket = conn.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
    if not ticket:
        conn.close()
        return jsonify({'success': False, 'error': 'Ticket nicht gefunden'})
    # Nur der Ticket-Owner oder Admin darf antworten
    if ticket['user_id'] != uid and not is_admin:
        conn.close()
        return jsonify({'success': False, 'error': 'Keine Berechtigung'})
    conn.execute(
        "INSERT INTO support_replies (ticket_id, sender_id, is_admin, message) VALUES (?,?,?,?)",
        (ticket_id, uid, 1 if is_admin else 0, message)
    )
    if is_admin:
        conn.execute("UPDATE support_tickets SET status='answered' WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()
    log_audit('support_reply', ticket_id)
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/support/ticket/<int:ticket_id>/close', methods=['POST'])
@login_required
def support_close_ticket(ticket_id):
    uid = session['user_id']
    conn = get_db()
    ticket = conn.execute("SELECT user_id FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
    if not ticket or (ticket['user_id'] != uid and not session.get('is_admin')):
        conn.close()
        return jsonify({'success': False})
    conn.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# Admin: Support-Ticket-Übersicht
@app.route('/admin/support')
@login_required
@admin_required
def admin_support():
    conn = get_db()
    tickets = conn.execute("""
        SELECT st.*, u.username,
               (SELECT COUNT(*) FROM support_replies WHERE ticket_id=st.id) as reply_count,
               (SELECT COUNT(*) FROM support_replies sr
                WHERE sr.ticket_id=st.id AND sr.is_admin=0 AND sr.read_at IS NULL) as unread_user
        FROM support_tickets st
        JOIN users u ON st.user_id=u.id
        ORDER BY CASE st.status WHEN 'open' THEN 0 WHEN 'answered' THEN 1 ELSE 2 END,
                 st.created_at DESC
    """).fetchall()
    conn.close()
    return render_template('admin_support.html', tickets=tickets)


@app.route('/admin/support/<int:ticket_id>')
@login_required
@admin_required
def admin_support_ticket(ticket_id):
    conn = get_db()
    ticket = conn.execute(
        "SELECT st.*, u.username FROM support_tickets st JOIN users u ON st.user_id=u.id WHERE st.id=?",
        (ticket_id,)
    ).fetchone()
    if not ticket:
        conn.close()
        abort(404)
    replies = conn.execute(
        "SELECT sr.*, u.username FROM support_replies sr "
        "JOIN users u ON sr.sender_id=u.id WHERE sr.ticket_id=? ORDER BY sr.created_at ASC",
        (ticket_id,)
    ).fetchall()
    # Admin liest → User-Nachrichten als gelesen markieren (aus Admin-Perspektive nicht nötig)
    conn.close()
    return render_template('admin_support_ticket.html', ticket=ticket, replies=replies)


@app.route('/profile/<username>')
def public_profile(username):
    """Zeigt ein öffentliches Profil eines Benutzers."""
    conn = get_db()
    user = conn.execute(
        "SELECT id, username FROM users WHERE username=? AND is_active=1", (username,)
    ).fetchone()
    if not user:
        abort(404)
    setting = conn.execute(
        "SELECT value FROM user_settings WHERE user_id=? AND key='public_profile'",
        (user['id'],)
    ).fetchone()
    if not setting or setting['value'] != 'true':
        abort(404)
    uid = user['id']
    viewer_id = session.get('user_id')
    year = datetime.now(timezone.utc).year

    # Follower / Following Zahlen
    follower_count = conn.execute(
        "SELECT COUNT(*) as c FROM follows WHERE followed_id=?", (uid,)
    ).fetchone()['c']
    following_count = conn.execute(
        "SELECT COUNT(*) as c FROM follows WHERE follower_id=?", (uid,)
    ).fetchone()['c']

    # Folgt der eingeloggte User diesem Profil?
    is_following = False
    if viewer_id and viewer_id != uid:
        is_following = bool(conn.execute(
            "SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",
            (viewer_id, uid)
        ).fetchone())

    books_reading = conn.execute(
        "SELECT b.title, b.cover_url, a.name as author FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? AND b.status='Reading' LIMIT 3", (uid,)
    ).fetchall()

    top_books = conn.execute(
        "SELECT b.title, b.cover_url, a.name as author FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN ratings r ON b.id=r.book_id "
        "WHERE b.user_id=? AND r.stars=5 ORDER BY b.read_date DESC LIMIT 5", (uid,)
    ).fetchall()

    year_stats = conn.execute(
        "SELECT COUNT(*) as books_read, COALESCE(SUM(b.pages),0) as pages_read "
        "FROM books b WHERE b.user_id=? AND strftime('%Y', b.read_date)=?",
        (uid, str(year))
    ).fetchone()

    # Gemeinsame Bücher (beide User haben das Buch gelesen)
    common_books = []
    if viewer_id and viewer_id != uid:
        common_books = conn.execute(
            "SELECT b.title, b.cover_url, a.name as author FROM books b "
            "LEFT JOIN authors a ON b.author_id=a.id "
            "WHERE b.user_id=? AND b.status='Read' AND b.title IN ("
            "  SELECT title FROM books WHERE user_id=? AND status='Read'"
            ") ORDER BY b.read_date DESC LIMIT 6",
            (uid, viewer_id)
        ).fetchall()

    # Lese-Duelle: abgeschlossene Buddy-Reads – wer war zuerst fertig?
    duels = conn.execute(
        "SELECT br.book_title, br.book_cover, "
        "       br.initiator_id, br.partner_id, "
        "       br.initiator_progress, br.partner_progress, "
        "       br.total_pages, br.updated_at, "
        "       u1.username as initiator_name, u2.username as partner_name "
        "FROM buddy_reads br "
        "JOIN users u1 ON br.initiator_id=u1.id "
        "JOIN users u2 ON br.partner_id=u2.id "
        "WHERE (br.initiator_id=? OR br.partner_id=?) AND br.status='finished' "
        "ORDER BY br.updated_at DESC LIMIT 5",
        (uid, uid)
    ).fetchall()

    # Duelle auswerten: Gewinner = wer zuerst total_pages erreicht hat
    duel_results = []
    for d in duels:
        if d['total_pages'] and d['total_pages'] > 0:
            i_pct = (d['initiator_progress'] or 0) / d['total_pages'] * 100
            p_pct = (d['partner_progress'] or 0) / d['total_pages'] * 100
            if i_pct >= 100 and p_pct >= 100:
                winner = d['initiator_name'] if d['initiator_id'] == uid else d['partner_name']
            elif i_pct >= 100:
                winner = d['initiator_name']
            elif p_pct >= 100:
                winner = d['partner_name']
            else:
                winner = None
            duel_results.append({
                'title': d['book_title'],
                'cover': d['book_cover'],
                'winner': winner,
                'is_winner': winner == user['username'],
                'initiator': d['initiator_name'],
                'partner': d['partner_name'],
            })

    conn.close()
    return render_template('public_profile.html',
        profile_user=user,
        books_reading=books_reading,
        top_books=top_books,
        year_stats=year_stats,
        year=year,
        follower_count=follower_count,
        following_count=following_count,
        is_following=is_following,
        viewer_id=viewer_id,
        common_books=common_books,
        duel_results=duel_results,
    )



@app.route('/buddies')
@login_required
def buddies():
    uid = session['user_id']
    conn = get_db()
    # Folge-Beziehungen
    following = conn.execute(
        "SELECT u.id, u.username FROM follows f JOIN users u ON f.followed_id=u.id WHERE f.follower_id=?", (uid,)
    ).fetchall()
    followers = conn.execute(
        "SELECT u.id, u.username FROM follows f JOIN users u ON f.follower_id=u.id WHERE f.followed_id=?", (uid,)
    ).fetchall()
    # Abgeschlossene und abgebrochene Buddy-Reads
    finished_reads = conn.execute(
        "SELECT br.*, u.username as partner_name FROM buddy_reads br "
        "JOIN users u ON (CASE WHEN br.initiator_id=? THEN br.partner_id ELSE br.initiator_id END)=u.id "
        "WHERE (br.initiator_id=? OR br.partner_id=?) AND br.status IN ('finished','abandoned') "
        "ORDER BY br.updated_at DESC LIMIT 20",
        (uid, uid, uid)
    ).fetchall()
    # Ausstehende Einladungen die ICH gesendet habe
    pending_out = conn.execute(
        "SELECT br.*, u.username as partner_name FROM buddy_reads br "
        "JOIN users u ON br.partner_id=u.id "
        "WHERE br.initiator_id=? AND br.status='pending' ORDER BY br.created_at DESC",
        (uid,)
    ).fetchall()
    # Aktive Buddy-Reads
    active_reads = conn.execute(
        "SELECT br.*, u.username as partner_name FROM buddy_reads br "
        "JOIN users u ON (CASE WHEN br.initiator_id=? THEN br.partner_id ELSE br.initiator_id END)=u.id "
        "WHERE (br.initiator_id=? OR br.partner_id=?) AND br.status='active'",
        (uid, uid, uid)
    ).fetchall()
    # Ausstehende Einladungen (eingehend)
    pending_in = conn.execute(
        "SELECT br.*, u.username as initiator_name FROM buddy_reads br "
        "JOIN users u ON br.initiator_id=u.id "
        "WHERE br.partner_id=? AND br.status='pending'", (uid,)
    ).fetchall()
    # Buddy-Vorschläge: User die das gleiche Buch auf der Wunschliste haben
    suggestions = conn.execute(
        """SELECT DISTINCT u.id, u.username, w.title as common_book
           FROM users u
           JOIN wishlist w ON w.user_id=u.id
           JOIN wishlist my_w ON my_w.user_id=? AND my_w.title=w.title
           WHERE u.id!=? AND u.is_active=1
           AND NOT EXISTS (SELECT 1 FROM follows WHERE follower_id=? AND followed_id=u.id)
           LIMIT 5""",
        (uid, uid, uid)
    ).fetchall()
    conn.close()
    return render_template('buddies.html',
        following=following, followers=followers,
        active_reads=active_reads, pending_in=pending_in, pending_out=pending_out,
        finished_reads=finished_reads, suggestions=suggestions)

@csrf.exempt
@app.route('/api/buddies/follow/<int:target_id>', methods=['POST'])
@login_required
def buddy_follow(target_id):
    uid = session['user_id']
    if uid == target_id:
        return jsonify({'error': 'Kann dir selbst nicht folgen'}), 400
    conn = get_db()
    existing = conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (uid, target_id)).fetchone()
    if existing:
        conn.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?", (uid, target_id))
        conn.commit(); conn.close()
        return jsonify({'success': True, 'following': False})
    conn.execute("INSERT INTO follows (follower_id, followed_id) VALUES (?,?)", (uid, target_id))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'following': True})

@csrf.exempt
@app.route('/api/buddies/invite', methods=['POST'])
@login_required
def buddy_invite():
    uid = session['user_id']
    data = request.get_json() or {}
    partner_id = data.get('partner_id')
    book_title = (data.get('book_title') or '').strip()
    book_cover = data.get('book_cover', '')
    total_pages = int(data.get('total_pages') or 0)
    if not partner_id or not book_title:
        return jsonify({'error': 'Partner und Buchtitel erforderlich'}), 400
    conn = get_db()
    # Kein doppeltes aktives Buddy-Read für dasselbe Buch
    existing = conn.execute(
        "SELECT id FROM buddy_reads WHERE ((initiator_id=? AND partner_id=?) OR (initiator_id=? AND partner_id=?)) AND status IN ('pending','active') AND book_title=?",
        (uid, partner_id, partner_id, uid, book_title)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Es gibt bereits eine aktive Einladung für dieses Buch'}), 409
    partner = conn.execute("SELECT id, username, email FROM users WHERE id=?", (partner_id,)).fetchone()
    if not partner:
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404
    conn.execute(
        "INSERT INTO buddy_reads (initiator_id, partner_id, book_title, book_cover, total_pages, status) VALUES (?,?,?,?,?,'pending')",
        (uid, partner_id, book_title, book_cover, total_pages)
    )
    conn.commit()
    conn.close()
    # E-Mail-Benachrichtigung
    from_username = session.get('username', 'Jemand')
    notify_buddy_request(partner_id, from_username, book_title)
    return jsonify({'success': True})

@csrf.exempt
@app.route('/api/buddies/respond/<int:read_id>', methods=['POST'])
@login_required
def buddy_respond(read_id):
    uid = session['user_id']
    data = request.get_json() or {}
    action = data.get('action')  # 'accept' or 'decline'
    conn = get_db()
    br = conn.execute("SELECT * FROM buddy_reads WHERE id=? AND partner_id=? AND status='pending'", (read_id, uid)).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Einladung nicht gefunden'}), 404
    new_status = 'active' if action == 'accept' else 'declined'
    conn.execute("UPDATE buddy_reads SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, read_id))
    conn.commit()
    initiator_id = br['initiator_id']
    book_title = br['book_title']
    conn.close()
    # E-Mail-Benachrichtigung bei Annahme
    if action == 'accept':
        notify_buddy_accepted(initiator_id, session.get('username', 'Jemand'), book_title)
    return jsonify({'success': True, 'status': new_status})

@app.route('/buddies/read/<int:read_id>')
@login_required
def buddy_read_detail(read_id):
    uid = session['user_id']
    conn = get_db()
    br = conn.execute(
        "SELECT br.*, ui.username as initiator_name, up.username as partner_name "
        "FROM buddy_reads br "
        "JOIN users ui ON br.initiator_id=ui.id "
        "JOIN users up ON br.partner_id=up.id "
        "WHERE br.id=? AND (br.initiator_id=? OR br.partner_id=?) AND br.status IN ('active','finished')",
        (read_id, uid, uid)
    ).fetchone()
    if not br:
        conn.close()
        abort(404)
    messages = conn.execute(
        "SELECT bm.*, u.username FROM buddy_messages bm JOIN users u ON bm.sender_id=u.id WHERE bm.buddy_read_id=? ORDER BY bm.created_at",
        (read_id,)
    ).fetchall()
    milestones = conn.execute(
        "SELECT * FROM buddy_milestones WHERE buddy_read_id=? ORDER BY target_page",
        (read_id,)
    ).fetchall()
    conn.close()
    is_initiator = (br['initiator_id'] == uid)
    return render_template('buddy_read.html',
        br=br, messages=messages, milestones=milestones,
        uid=uid, is_initiator=is_initiator)

@csrf.exempt
@app.route('/api/buddies/read/<int:read_id>/progress', methods=['POST'])
@login_required
def buddy_update_progress(read_id):
    uid = session['user_id']
    data = request.get_json() or {}
    page = int(data.get('page') or 0)
    waiting = data.get('waiting', False)
    conn = get_db()
    br = conn.execute("SELECT * FROM buddy_reads WHERE id=? AND (initiator_id=? OR partner_id=?) AND status='active'", (read_id, uid, uid)).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    field = 'initiator_page' if br['initiator_id'] == uid else 'partner_page'
    conn.execute(f"UPDATE buddy_reads SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (page, read_id))
    conn.commit()
    # Meilensteine prüfen
    milestones = conn.execute(
        "SELECT * FROM buddy_milestones WHERE buddy_read_id=? AND target_page<=?", (read_id, page)
    ).fetchall()
    for m in milestones:
        col = 'completed_by_initiator' if br['initiator_id'] == uid else 'completed_by_partner'
        conn.execute(f"UPDATE buddy_milestones SET {col}=1 WHERE id=?", (m['id'],))
    conn.commit()
    # Meilenstein-Emails senden
    for m in milestones:
        partner_uid = br['partner_id'] if br['initiator_id'] == uid else br['initiator_id']
        notify_buddy_milestone(partner_uid, session.get('username', '?'), br['book_title'], m['description'])
    conn.commit()
    updated = conn.execute("SELECT * FROM buddy_reads WHERE id=?", (read_id,)).fetchone()
    # Buddy-Read als fertig markieren wenn beide total_pages erreicht
    finished = False
    if br['total_pages'] and br['total_pages'] > 0:
        i_done = (updated['initiator_page'] or 0) >= br['total_pages']
        p_done = (updated['partner_page'] or 0) >= br['total_pages']
        if i_done and p_done:
            conn.execute("UPDATE buddy_reads SET status='finished', updated_at=CURRENT_TIMESTAMP WHERE id=?", (read_id,))
            conn.commit()
            finished = True
        elif i_done or p_done:
            # Einer fertig – Buddy benachrichtigen
            partner_uid = br['partner_id'] if br['initiator_id'] == uid else br['initiator_id']
            notify_buddy_finished(partner_uid, session.get('username', '?'), br['book_title'])
    conn.close()
    return jsonify({
        'success': True,
        'initiator_page': updated['initiator_page'],
        'partner_page': updated['partner_page'],
        'waiting': waiting,
        'finished': finished
    })

@csrf.exempt
@app.route('/api/buddies/read/<int:read_id>/message', methods=['POST'])
@login_required
def buddy_send_message(read_id):
    uid = session['user_id']
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    is_spoiler = 1 if data.get('is_spoiler') else 0
    if not content:
        return jsonify({'error': 'Nachricht leer'}), 400
    conn = get_db()
    br = conn.execute("SELECT id FROM buddy_reads WHERE id=? AND (initiator_id=? OR partner_id=?) AND status='active'", (read_id, uid, uid)).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Nicht erlaubt'}), 403
    conn.execute(
        "INSERT INTO buddy_messages (buddy_read_id, sender_id, content, is_spoiler) VALUES (?,?,?,?)",
        (read_id, uid, content, is_spoiler)
    )
    conn.commit()
    msgs = conn.execute(
        "SELECT bm.id, bm.content, bm.is_spoiler, bm.created_at, u.username FROM buddy_messages bm JOIN users u ON bm.sender_id=u.id WHERE bm.buddy_read_id=? ORDER BY bm.created_at DESC LIMIT 50",
        (read_id,)
    ).fetchall()
    conn.close()
    return jsonify({'success': True, 'messages': [dict(m) for m in reversed(msgs)]})

@csrf.exempt
@app.route('/api/buddies/read/<int:read_id>/milestone', methods=['POST'])
@login_required
def buddy_add_milestone(read_id):
    uid = session['user_id']
    data = request.get_json() or {}
    description = (data.get('description') or '').strip()
    target_page = int(data.get('target_page') or 0)
    if not description:
        return jsonify({'error': 'Beschreibung erforderlich'}), 400
    conn = get_db()
    br = conn.execute("SELECT id FROM buddy_reads WHERE id=? AND (initiator_id=? OR partner_id=?) AND status='active'", (read_id, uid, uid)).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Nicht erlaubt'}), 403
    conn.execute(
        "INSERT INTO buddy_milestones (buddy_read_id, creator_id, description, target_page) VALUES (?,?,?,?)",
        (read_id, uid, description, target_page)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/buddies/search-users')
@login_required
def buddy_search_users():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    uid = session['user_id']
    conn = get_db()
    users = conn.execute(
        "SELECT id, username FROM users WHERE username LIKE ? AND id!=? AND is_active=1 LIMIT 10",
        (f'%{q}%', uid)
    ).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@csrf.exempt
@app.route('/api/buddies/read/<int:read_id>/cancel', methods=['POST'])
@login_required
def buddy_cancel(read_id):
    """Ausstehende Einladung zurückziehen (nur Initiator)."""
    uid = session['user_id']
    conn = get_db()
    br = conn.execute(
        "SELECT * FROM buddy_reads WHERE id=? AND initiator_id=? AND status='pending'",
        (read_id, uid)
    ).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Einladung nicht gefunden'}), 404
    conn.execute("UPDATE buddy_reads SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE id=?", (read_id,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@csrf.exempt
@app.route('/api/buddies/read/<int:read_id>/abandon', methods=['POST'])
@login_required
def buddy_abandon(read_id):
    """Aktiven Buddy-Read abbrechen (beide Teilnehmer können das)."""
    uid = session['user_id']
    conn = get_db()
    br = conn.execute(
        "SELECT * FROM buddy_reads WHERE id=? AND (initiator_id=? OR partner_id=?) AND status='active'",
        (read_id, uid, uid)
    ).fetchone()
    if not br:
        conn.close()
        return jsonify({'error': 'Buddy-Read nicht gefunden'}), 404
    conn.execute("UPDATE buddy_reads SET status='abandoned', updated_at=CURRENT_TIMESTAMP WHERE id=?", (read_id,))
    conn.commit()
    # Partner benachrichtigen
    partner_uid = br['partner_id'] if br['initiator_id'] == uid else br['initiator_id']
    book_title = br['book_title']
    conn.close()
    try:
        conn2 = get_db()
        partner = conn2.execute("SELECT email, username FROM users WHERE id=?", (partner_uid,)).fetchone()
        conn2.close()
        if partner and partner['email']:
            html = f"""<div style="font-family:sans-serif;background:#0f172a;color:#f1f5f9;padding:2rem;border-radius:12px;">
  <h2 style="color:#ef4444;">📚 Reading Diary</h2>
  <p>Hey <strong>{partner['username']}</strong>,</p>
  <p><strong>{session.get('username','?')}</strong> hat den Buddy-Read abgebrochen:</p>
  <div style="background:#1e293b;padding:1rem;border-radius:8px;border-left:4px solid #ef4444;">
    <strong>📖 {book_title}</strong>
  </div>
</div>"""
            send_email(partner['email'], f"❌ Buddy-Read abgebrochen: {book_title}", html)
    except Exception:
        pass
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Notification Preferences
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/notification-prefs', methods=['GET', 'POST'])
@login_required
def notification_prefs_api():
    """Verwaltet Benachrichtigungseinstellungen."""
    uid = session['user_id']
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute(
            "SELECT pref_key, enabled FROM notification_prefs WHERE user_id=?", (uid,)
        ).fetchall()
        conn.close()
        defaults = {
            'buddy_request': 1, 'buddy_milestone': 1,
            'password_reset': 1, 'email_verify': 1,
        }
        prefs = {r['pref_key']: r['enabled'] for r in rows}
        for k, v in defaults.items():
            if k not in prefs:
                prefs[k] = v
        return jsonify(prefs)
    data = request.get_json() or {}
    for key, val in data.items():
        conn.execute(
            "INSERT OR REPLACE INTO notification_prefs (user_id, pref_key, enabled) VALUES (?,?,?)",
            (uid, key, 1 if val else 0)
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" ISBN lookup
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/isbn-lookup', methods=['POST'])
@login_required
def isbn_lookup():
    isbn = request.json.get('isbn', '').replace('-', '').replace(' ', '')
    if not isbn:
        return jsonify({'error': 'Keine ISBN angegeben'}), 400

    data = {}

    # 1) Google Books (no key required for basic usage)
    try:
        r = requests.get(
            f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}',
            timeout=6
        )
        if r.status_code == 200:
            gb = r.json()
            if gb.get('totalItems', 0) > 0:
                info = gb['items'][0]['volumeInfo']
                data['title'] = info.get('title', '')
                data['author'] = ', '.join(info.get('authors', []))
                data['publisher'] = info.get('publisher', '')
                data['pages'] = info.get('pageCount', '') or ''
                data['genre'] = ', '.join(info.get('categories', []))
                data['release_date'] = info.get('publishedDate', '')
                il = info.get('imageLinks', {})
                if il.get('thumbnail'):
                    data['cover_url'] = il['thumbnail'].replace('http://', 'https://')
                data['isbn'] = isbn
    except Exception:
        pass

    # 2) Open Library (supplement cover / missing fields)
    try:
        r = requests.get(
            f'https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data',
            timeout=6
        )
        if r.status_code == 200:
            ol = r.json().get(f'ISBN:{isbn}', {})
            if ol:
                data.setdefault('title', ol.get('title', ''))
                data.setdefault('author', ', '.join(a['name'] for a in ol.get('authors', [])))
                data.setdefault('publisher', ', '.join(p['name'] for p in ol.get('publishers', [])))
                data.setdefault('pages', ol.get('number_of_pages', ''))
                if not data.get('cover_url') and ol.get('cover'):
                    data['cover_url'] = ol['cover'].get('large') or ol['cover'].get('medium', '')
                data['isbn'] = isbn
    except Exception:
        pass

    # 3) Open Library search fallback
    if not data.get('title'):
        try:
            r = requests.get(
                f'https://openlibrary.org/search.json?isbn={isbn}&limit=1',
                timeout=6
            )
            if r.status_code == 200:
                docs = r.json().get('docs', [])
                if docs:
                    doc = docs[0]
                    data['title'] = doc.get('title', '')
                    data['author'] = ', '.join(doc.get('author_name', []))
                    data['publisher'] = ', '.join(doc.get('publisher', [])[:1])
                    data['pages'] = doc.get('number_of_pages_median', '')
                    data['genre'] = ', '.join(doc.get('subject', [])[:3])
                    if doc.get('cover_i') and not data.get('cover_url'):
                        data['cover_url'] = f'https://covers.openlibrary.org/b/id/{doc["cover_i"]}-L.jpg'
                    data['isbn'] = isbn
        except Exception:
            pass

    # Cover lokal speichern
    if data.get('cover_url') and data['cover_url'].startswith('http'):
        try:
            cr = requests.get(data['cover_url'], timeout=8, stream=True)
            if cr.status_code == 200:
                ct = cr.headers.get('content-type', 'image/jpeg').lower()
                ext = 'jpg'
                if 'png' in ct:
                    ext = 'png'
                elif 'gif' in ct:
                    ext = 'gif'
                elif 'webp' in ct:
                    ext = 'webp'
                fname = str(uuid.uuid4()) + '.' + ext
                upload_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'static', 'uploads', 'covers')
                os.makedirs(upload_dir, exist_ok=True)
                with open(os.path.join(upload_dir, fname), 'wb') as fh:
                    for chunk in cr.iter_content(65536):
                        fh.write(chunk)
                data['cover_url'] = f'/static/uploads/covers/{fname}'
        except Exception:
            pass

    if data:
        return jsonify(data)
    return jsonify({'error': 'Buch nicht gefunden', 'isbn': isbn}), 404


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Cover Upload
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/upload-cover', methods=['POST'])
@login_required
def upload_cover():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Dateiname fehlt'}), 400
    allowed = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'UngÃ¼ltiger Dateityp. Erlaubt: jpg, png, gif, webp'}), 400
    fname = str(uuid.uuid4()) + '.' + ext
    upload_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'static', 'uploads', 'covers')
    os.makedirs(upload_dir, exist_ok=True)
    f.save(os.path.join(upload_dir, fname))
    return jsonify({'url': f'/static/uploads/covers/{fname}'})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Authors / Publishers
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/authors/search')
@login_required
def search_authors():
    q = request.args.get('q', '')
    uid = session['user_id']
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM authors WHERE user_id=? AND name LIKE ? ORDER BY name LIMIT 10",
        (uid, f'%{q}%')
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@csrf.exempt
@app.route('/api/genres/search')
@login_required
def search_genres():
    q = request.args.get('q', '')
    conn = get_db()
    # Collect distinct genre tokens from both books and wishlist
    rows = conn.execute(
        "SELECT DISTINCT genre FROM books WHERE genre IS NOT NULL AND genre != '' "
        "UNION SELECT DISTINCT genre FROM wishlist WHERE genre IS NOT NULL AND genre != ''"
    ).fetchall()
    conn.close()
    seen, results = set(), []
    for r in rows:
        for token in (t.strip() for t in r['genre'].split(',') if t.strip()):
            key = token.lower()
            if key not in seen and (not q or q.lower() in key):
                seen.add(key)
                results.append({'id': token, 'name': token})
    results.sort(key=lambda x: x['name'])
    return jsonify(results[:15])


@csrf.exempt
@app.route('/api/publishers/search')
@login_required
def search_publishers():
    q = request.args.get('q', '')
    uid = session['user_id']
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM publishers WHERE user_id=? AND name LIKE ? ORDER BY name LIMIT 10",
        (uid, f'%{q}%')
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@csrf.exempt
@app.route('/api/authors/<int:aid>', methods=['DELETE'])
@login_required
def delete_author(aid):
    conn = get_db()
    c = conn.execute("SELECT COUNT(*) as c FROM books WHERE author_id=?", (aid,)).fetchone()['c']
    w = conn.execute("SELECT COUNT(*) as c FROM wishlist WHERE author_id=?", (aid,)).fetchone()['c']
    if c + w > 0:
        conn.close()
        return jsonify({'error': f'Autor wird noch von {c + w} EintrÃ¤gen verwendet'}), 400
    conn.execute("DELETE FROM authors WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/publishers/<int:pid>', methods=['DELETE'])
@login_required
def delete_publisher(pid):
    conn = get_db()
    c = conn.execute("SELECT COUNT(*) as c FROM books WHERE publisher_id=?", (pid,)).fetchone()['c']
    w = conn.execute("SELECT COUNT(*) as c FROM wishlist WHERE publisher_id=?", (pid,)).fetchone()['c']
    if c + w > 0:
        conn.close()
        return jsonify({'error': f'Verlag wird noch von {c + w} EintrÃ¤gen verwendet'}), 400
    conn.execute("DELETE FROM publishers WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Books
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/books', methods=['POST'])
@login_required
def create_book():
    d = request.json
    uid = session['user_id']
    conn = get_db()
    aid = upsert_author(conn, d.get('author', ''), uid)
    pid = upsert_publisher(conn, d.get('publisher', ''), uid)
    conn.execute(
        "INSERT INTO books (user_id, title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, format, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
         d.get('pages') or 0, d.get('format', 'Paperback'), d.get('release_date'),
         d.get('series'), d.get('volume'), d.get('status', 'Ungelesen'),
         1 if d.get('is_audiobook') else 0)
    )
    book_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': book_id, 'success': True})


@csrf.exempt
@app.route('/api/books/<int:book_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def book_api(book_id):
    uid = session['user_id']
    conn = get_db()
    if request.method == 'GET':
        book = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id WHERE b.id=? AND b.user_id=?", (book_id, uid)
        ).fetchone()
        conn.close()
        return jsonify(dict(book)) if book else (jsonify({'error': 'Nicht gefunden'}), 404)

    elif request.method == 'PUT':
        d = request.json
        aid = upsert_author(conn, d.get('author', ''), uid)
        pid = upsert_publisher(conn, d.get('publisher', ''), uid)
        existing = conn.execute("SELECT status, read_date FROM books WHERE id=? AND user_id=?", (book_id, uid)).fetchone()
        read_date = existing['read_date'] if existing else None
        if d.get('status') == 'Gelesen' and existing and existing['status'] != 'Gelesen':
            read_date = datetime.now(timezone.utc).isoformat()
        elif d.get('status') != 'Gelesen':
            read_date = None
        conn.execute(
            "UPDATE books SET title=?, author_id=?, publisher_id=?, isbn=?, cover_url=?, "
            "genre=?, pages=?, format=?, release_date=?, series=?, volume=?, status=?, read_date=?, is_audiobook=? "
            "WHERE id=? AND user_id=?",
            (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
             d.get('pages') or 0, d.get('format', 'Paperback'), d.get('release_date'),
             d.get('series'), d.get('volume'), d.get('status', 'Ungelesen'), read_date,
             1 if d.get('is_audiobook') else 0, book_id, uid)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    elif request.method == 'DELETE':
        conn.execute("DELETE FROM books WHERE id=? AND user_id=?", (book_id, uid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})


@csrf.exempt
@app.route('/api/books/<int:book_id>/progress', methods=['POST'])
@login_required
def add_progress(book_id):
    d = request.json
    new_page = int(d.get('page', 0))
    conn = get_db()
    last = conn.execute(
        "SELECT page FROM reading_progress WHERE book_id=? ORDER BY timestamp DESC LIMIT 1",
        (book_id,)
    ).fetchone()
    prev_page = last['page'] if last else 0
    delta = new_page - prev_page
    conn.execute(
        "INSERT INTO reading_progress (book_id, page, delta) VALUES (?,?,?)",
        (book_id, new_page, delta)
    )
    book = conn.execute("SELECT pages FROM books WHERE id=?", (book_id,)).fetchone()
    if book and book['pages'] and new_page >= book['pages']:
        conn.execute(
            "UPDATE books SET status='Gelesen', read_date=? WHERE id=? AND status!='Gelesen'",
            (datetime.now(timezone.utc).isoformat(), book_id)
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'delta': delta, 'page': new_page})


@csrf.exempt
@app.route('/api/books/<int:book_id>/audio-progress', methods=['POST'])
@login_required
def add_audio_progress(book_id):
    d = request.json
    new_percent = max(0, min(100, int(d.get('percent', 0))))
    conn = get_db()
    last = conn.execute(
        "SELECT percent FROM audio_progress WHERE book_id=? ORDER BY timestamp DESC LIMIT 1",
        (book_id,)
    ).fetchone()
    prev_percent = last['percent'] if last else 0
    delta = new_percent - prev_percent
    conn.execute(
        "INSERT INTO audio_progress (book_id, percent, delta) VALUES (?,?,?)",
        (book_id, new_percent, delta)
    )
    if new_percent >= 100:
        conn.execute(
            "UPDATE books SET status='Gelesen', read_date=? WHERE id=? AND status!='Gelesen'",
            (datetime.now(timezone.utc).isoformat(), book_id)
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'delta': delta, 'percent': new_percent})


@csrf.exempt
@app.route('/api/books/<int:book_id>/rating', methods=['PUT'])
@login_required
def update_rating(book_id):
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO ratings (book_id, stars, spice, tension, type) VALUES (?,?,?,?,?)",
        (book_id, d.get('stars', 0), d.get('spice', 0), d.get('tension', 0), d.get('type', 'Fiction'))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/books/<int:book_id>/review', methods=['PUT'])
@login_required
def update_review(book_id):
    d = request.json
    conn = get_db()
    if get_setting(conn, 'show_reviews', 'true') != 'true':
        conn.close()
        return jsonify({'error': 'Rezensionen sind deaktiviert'}), 403
    conn.execute(
        "INSERT OR REPLACE INTO reviews (book_id, content, updated_at) VALUES (?,?,?)",
        (book_id, d.get('content', ''), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Wishlist
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/wishlist', methods=['POST'])
@login_required
def create_wishlist():
    d = request.json
    uid = session['user_id']
    conn = get_db()
    aid = upsert_author(conn, d.get('author', ''), uid)
    pid = upsert_publisher(conn, d.get('publisher', ''), uid)
    conn.execute(
        "INSERT INTO wishlist (user_id, title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
         d.get('pages') or 0, d.get('release_date'), d.get('series'), d.get('volume'),
         d.get('status', 'Ungelesen'), 1 if d.get('is_audiobook') else 0)
    )
    wid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': wid, 'success': True})


@csrf.exempt
@app.route('/api/wishlist/<int:wid>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def wishlist_api(wid):
    uid = session['user_id']
    conn = get_db()
    if request.method == 'GET':
        item = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id WHERE w.id=? AND w.user_id=?", (wid, uid)
        ).fetchone()
        conn.close()
        return jsonify(dict(item)) if item else (jsonify({'error': 'Nicht gefunden'}), 404)

    elif request.method == 'PUT':
        d = request.json
        aid = upsert_author(conn, d.get('author', ''), uid)
        pid = upsert_publisher(conn, d.get('publisher', ''), uid)
        conn.execute(
            "UPDATE wishlist SET title=?, author_id=?, publisher_id=?, isbn=?, cover_url=?, "
            "genre=?, pages=?, release_date=?, series=?, volume=?, status=?, is_audiobook=? WHERE id=? AND user_id=?",
            (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
             d.get('pages') or 0, d.get('release_date'), d.get('series'), d.get('volume'),
             d.get('status', 'Ungelesen'), 1 if d.get('is_audiobook') else 0, wid, uid)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    elif request.method == 'DELETE':
        conn.execute("DELETE FROM wishlist WHERE id=? AND user_id=?", (wid, uid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})


@csrf.exempt
@app.route('/api/wishlist/<int:wid>/buy', methods=['POST'])
@login_required
def buy_wishlist(wid):
    d = request.json
    uid = session['user_id']
    fmt = d.get('format', 'Paperback')
    conn = get_db()
    item = conn.execute("SELECT * FROM wishlist WHERE id=? AND user_id=?", (wid, uid)).fetchone()
    if not item:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    conn.execute(
        "INSERT INTO books (user_id, title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, format, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, item['title'], item['author_id'], item['publisher_id'], item['isbn'],
         item['cover_url'], item['genre'], item['pages'], fmt,
         item['release_date'], item['series'], item['volume'], item['status'],
         item['is_audiobook'] if 'is_audiobook' in item.keys() else 0)
    )
    book_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.execute("DELETE FROM wishlist WHERE id=? AND user_id=?", (wid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'book_id': book_id})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Quotes
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/quotes', methods=['POST'])
@login_required
def create_quote():
    d = request.json
    uid = session['user_id']
    book_id = d.get('book_id')
    conn = get_db()
    book = conn.execute("SELECT id FROM books WHERE id=? AND user_id=?", (book_id, uid)).fetchone()
    if not book:
        conn.close()
        return jsonify({'error': 'Buch nicht gefunden'}), 404
    conn.execute(
        "INSERT INTO quotes (book_id, quote_text, page) VALUES (?,?,?)",
        (book_id, d.get('quote_text', ''), d.get('page'))
    )
    qid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': qid, 'success': True})


@csrf.exempt
@app.route('/api/quotes/<int:qid>', methods=['DELETE'])
@login_required
def delete_quote(qid):
    uid = session['user_id']
    conn = get_db()
    conn.execute(
        "DELETE FROM quotes WHERE id=? AND book_id IN (SELECT id FROM books WHERE user_id=?)",
        (qid, uid)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Settings
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    d = request.json
    uid = session['user_id']
    conn = get_db()
    for key, value in d.items():
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?,?,?)",
            (uid, key, str(value))
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/settings/language', methods=['POST'])
@login_required
def set_language():
    lang = (request.json or {}).get('lang', 'de')
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'de'
    uid = session['user_id']
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?,?,?)",
        (uid, 'language', lang)
    )
    conn.commit()
    conn.close()
    session['language'] = lang
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/settings/password', methods=['POST'])
@login_required
def change_password():
    d = request.json or {}
    current_pw = d.get('current', '')
    new_pw = d.get('new', '').strip()
    uid = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not user or not verify_pw(user['password_hash'], current_pw):
        return jsonify({'error': 'Aktuelles Passwort ist falsch'}), 400
    ok, msg = validate_password_strength(new_pw)
    if not ok:
        return jsonify({'error': msg}), 400
    new_hash = hash_pw(new_pw)
    conn = get_db()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Reading Goals
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/reading-goals', methods=['POST'])
@login_required
def create_goal():
    d = request.json
    uid = session['user_id']
    conn = get_db()
    conn.execute("UPDATE reading_goals SET enabled=0 WHERE user_id=?", (uid,))
    conn.execute(
        "INSERT INTO reading_goals (user_id, goal_type, period, target, enabled) VALUES (?,?,?,?,1)",
        (uid, d.get('goal_type'), d.get('period'), d.get('target'))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/reading-goals/<int:gid>/toggle', methods=['POST'])
@login_required
def toggle_goal(gid):
    uid = session['user_id']
    conn = get_db()
    row = conn.execute("SELECT enabled FROM reading_goals WHERE id=? AND user_id=?", (gid, uid)).fetchone()
    if row:
        new_val = 0 if row['enabled'] else 1
        if new_val == 1:
            conn.execute("UPDATE reading_goals SET enabled=0 WHERE user_id=?", (uid,))
        conn.execute("UPDATE reading_goals SET enabled=? WHERE id=? AND user_id=?", (new_val, gid, uid))
        conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/reading-goals/<int:gid>', methods=['DELETE'])
@login_required
def delete_goal(gid):
    uid = session['user_id']
    conn = get_db()
    conn.execute("DELETE FROM reading_goals WHERE id=? AND user_id=?", (gid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Statistics charts
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/statistics/charts')
@login_required
def stats_charts():
    uid = session['user_id']
    conn = get_db()
    period = request.args.get('period', 'monthly')
    now = datetime.now(timezone.utc)
    months_de = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

    labels, pages_data, books_data = [], [], []

    audio_books_data = []

    if period == 'weekly':
        for i in range(7, -1, -1):
            ws = now - timedelta(days=now.weekday() + 7 * i)
            ws = ws.replace(hour=0, minute=0, second=0, microsecond=0)
            we = ws + timedelta(days=7)
            labels.append(f"KW {ws.isocalendar()[1]}")
            p = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as v "
                "FROM reading_progress rp JOIN books b ON b.id=rp.book_id "
                "WHERE b.user_id=? AND rp.timestamp>=? AND rp.timestamp<?",
                (uid, ws.isoformat(), we.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=0 "
                "AND read_date>=? AND read_date<?",
                (uid, ws.isoformat(), we.isoformat())
            ).fetchone()['v']
            books_data.append(b)
            ab = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=1 "
                "AND read_date>=? AND read_date<?",
                (uid, ws.isoformat(), we.isoformat())
            ).fetchone()['v']
            audio_books_data.append(ab)

    elif period == 'monthly':
        for i in range(11, -1, -1):
            m = now.month - i
            y = now.year
            while m <= 0:
                m += 12
                y -= 1
            nm = m + 1
            ny = y
            if nm > 12:
                nm = 1
                ny += 1
            start = datetime(y, m, 1)
            end = datetime(ny, nm, 1)
            labels.append(f"{months_de[m-1]} {y}")
            p = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as v "
                "FROM reading_progress rp JOIN books b ON b.id=rp.book_id "
                "WHERE b.user_id=? AND rp.timestamp>=? AND rp.timestamp<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=0 "
                "AND read_date>=? AND read_date<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            books_data.append(b)
            ab = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=1 "
                "AND read_date>=? AND read_date<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            audio_books_data.append(ab)

    else:  # yearly
        for i in range(4, -1, -1):
            y = now.year - i
            start = datetime(y, 1, 1)
            end = datetime(y + 1, 1, 1)
            labels.append(str(y))
            p = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as v "
                "FROM reading_progress rp JOIN books b ON b.id=rp.book_id "
                "WHERE b.user_id=? AND rp.timestamp>=? AND rp.timestamp<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=0 "
                "AND read_date>=? AND read_date<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            books_data.append(b)
            ab = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE user_id=? AND status='Gelesen' AND is_audiobook=1 "
                "AND read_date>=? AND read_date<?",
                (uid, start.isoformat(), end.isoformat())
            ).fetchone()['v']
            audio_books_data.append(ab)

    conn.close()
    return jsonify({'labels': labels, 'pages': pages_data, 'books': books_data, 'audio_books': audio_books_data})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  Serien
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route('/series')
@login_required
def series_list():
    uid = session['user_id']
    conn = get_db()
    series = conn.execute(
        "SELECT s.*, COUNT(b.id) as total, "
        "SUM(CASE WHEN b.status='Gelesen' THEN 1 ELSE 0 END) as read_count "
        "FROM series s LEFT JOIN books b ON b.series_id=s.id AND b.user_id=? "
        "WHERE s.user_id=? "
        "GROUP BY s.id ORDER BY s.name",
        (uid, uid)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id WHERE b.user_id=? ORDER BY b.title",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template('series.html', series=series, all_books=all_books)


@app.route('/series/<int:sid>')
@login_required
def series_detail(sid):
    uid = session['user_id']
    conn = get_db()
    s = conn.execute("SELECT * FROM series WHERE id=? AND user_id=?", (sid, uid)).fetchone()
    if not s:
        conn.close()
        return redirect(url_for('series_list'))
    books = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.series_id=? AND b.user_id=? ORDER BY COALESCE(b.series_order, 9999), b.id",
        (sid, uid)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, b.cover_url, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? AND (b.series_id IS NULL OR b.series_id != ?) "
        "ORDER BY b.title",
        (uid, sid)
    ).fetchall()
    conn.close()
    return render_template('series_detail.html', series=s, books=books, all_books=all_books)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  Regale
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route('/shelves')
@login_required
def shelves():
    uid = session['user_id']
    conn = get_db()
    shelves_list = conn.execute(
        "SELECT s.*, COUNT(sb.book_id) as book_count "
        "FROM shelves s LEFT JOIN shelf_books sb ON sb.shelf_id=s.id "
        "WHERE s.user_id=? "
        "GROUP BY s.id ORDER BY s.name",
        (uid,)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id WHERE b.user_id=? ORDER BY b.title",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template('shelves.html', shelves=shelves_list, all_books=all_books)


@app.route('/shelves/<int:shid>')
@login_required
def shelf_detail(shid):
    uid = session['user_id']
    conn = get_db()
    shelf = conn.execute("SELECT * FROM shelves WHERE id=? AND user_id=?", (shid, uid)).fetchone()
    if not shelf:
        conn.close()
        return redirect(url_for('shelves'))
    books = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "JOIN shelf_books sb ON sb.book_id=b.id "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE sb.shelf_id=? AND b.user_id=? ORDER BY b.title",
        (shid, uid)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, b.cover_url, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? ORDER BY b.title",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template('shelf_detail.html', shelf=shelf, books=books, all_books=all_books)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  JahresrÃ¼ckblick
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route('/stats/year/<int:year>')
@login_required
def year_review(year):
    uid = session['user_id']
    conn = get_db()
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    books_read = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.user_id=? AND b.status='Gelesen' AND b.read_date >= ? AND b.read_date < ? "
        "ORDER BY b.read_date",
        (uid, start.isoformat(), end.isoformat())
    ).fetchall()
    total_pages = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as t "
        "FROM reading_progress rp JOIN books b ON b.id=rp.book_id "
        "WHERE b.user_id=? AND rp.timestamp >= ? AND rp.timestamp < ?",
        (uid, start.isoformat(), end.isoformat())
    ).fetchone()['t']
    genres = {}
    for b in books_read:
        if b['genre']:
            for g in b['genre'].split(','):
                g = g.strip()
                if g:
                    genres[g] = genres.get(g, 0) + 1
    top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:5]
    months_de = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
    monthly = []
    for m in range(1, 13):
        ms = datetime(year, m, 1)
        me = datetime(year, m + 1, 1) if m < 12 else end
        c = conn.execute(
            "SELECT COUNT(*) as c FROM books WHERE user_id=? AND status='Gelesen' "
            "AND read_date >= ? AND read_date < ?",
            (uid, ms.isoformat(), me.isoformat())
        ).fetchone()['c']
        monthly.append({'label': months_de[m - 1], 'count': c})
    best = conn.execute(
        "SELECT b.*, a.name as author_name, r.stars FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN ratings r ON r.book_id=b.id "
        "WHERE b.user_id=? AND b.status='Gelesen' AND b.read_date >= ? AND b.read_date < ? "
        "AND r.stars IS NOT NULL ORDER BY r.stars DESC LIMIT 1",
        (uid, start.isoformat(), end.isoformat())
    ).fetchone()
    years_rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', read_date) as y FROM books "
        "WHERE user_id=? AND status='Gelesen' AND read_date IS NOT NULL ORDER BY y DESC",
        (uid,)
    ).fetchall()
    available_years = [int(r['y']) for r in years_rows if r['y']]
    conn.close()
    return render_template('year_review.html',
                           year=year,
                           books_read=books_read,
                           total_pages=total_pages,
                           top_genres=top_genres,
                           monthly=monthly,
                           best=best,
                           available_years=available_years)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  Export
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@app.route('/export/csv')
@login_required
def export_csv():
    uid = session['user_id']
    conn = get_db()
    books = conn.execute(
        "SELECT b.title, a.name as author, p.name as publisher, b.isbn, "
        "b.genre, b.pages, b.format, b.release_date, b.series, b.volume, "
        "b.status, b.read_date, b.added_date, b.lent_to, b.lent_date "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id WHERE b.user_id=? ORDER BY b.added_date DESC",
        (uid,)
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Titel', 'Autor', 'Verlag', 'ISBN', 'Genre', 'Seiten', 'Format',
                     'Erscheinungsdatum', 'Reihe', 'Band', 'Status', 'Gelesen am',
                     'HinzugefÃ¼gt am', 'Verliehen an', 'Verliehen am'])
    for b in books:
        writer.writerow([b['title'], b['author'], b['publisher'], b['isbn'],
                         b['genre'], b['pages'], b['format'], b['release_date'],
                         b['series'], b['volume'], b['status'], b['read_date'],
                         b['added_date'], b['lent_to'], b['lent_date']])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment;filename=reading_diary.csv'}
    )


@app.route('/export/json')
@login_required
def export_json():
    uid = session['user_id']
    conn = get_db()
    books = conn.execute(
        "SELECT b.*, a.name as author_name, p.name as publisher_name "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id WHERE b.user_id=? ORDER BY b.added_date DESC",
        (uid,)
    ).fetchall()
    conn.close()
    data = [dict(b) for b in books]
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=reading_diary.json'}
    )


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Buchnotizen
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/books/<int:book_id>/notes', methods=['GET', 'POST'])
@login_required
def book_notes(book_id):
    uid = session['user_id']
    conn = get_db()
    if request.method == 'GET':
        notes = conn.execute(
            "SELECT n.* FROM book_notes n JOIN books b ON b.id=n.book_id "
            "WHERE n.book_id=? AND b.user_id=? ORDER BY n.created_at ASC",
            (book_id, uid)
        ).fetchall()
        conn.close()
        return jsonify([dict(n) for n in notes])
    d = request.json
    book = conn.execute("SELECT id FROM books WHERE id=? AND user_id=?", (book_id, uid)).fetchone()
    if not book:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    conn.execute(
        "INSERT INTO book_notes (book_id, chapter, content) VALUES (?,?,?)",
        (book_id, (d.get('chapter') or '').strip(), d.get('content', ''))
    )
    nid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': nid, 'success': True})


@csrf.exempt
@app.route('/api/notes/<int:nid>', methods=['PUT', 'DELETE'])
@login_required
def note_api(nid):
    uid = session['user_id']
    conn = get_db()
    if request.method == 'PUT':
        d = request.json
        note = conn.execute(
            "SELECT n.id FROM book_notes n JOIN books b ON b.id=n.book_id WHERE n.id=? AND b.user_id=?",
            (nid, uid)
        ).fetchone()
        if not note:
            conn.close()
            return jsonify({'error': 'Nicht gefunden'}), 404
        conn.execute(
            "UPDATE book_notes SET chapter=?, content=? WHERE id=?",
            ((d.get('chapter') or '').strip(), d.get('content', ''), nid)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    note = conn.execute(
        "SELECT n.id FROM book_notes n JOIN books b ON b.id=n.book_id WHERE n.id=? AND b.user_id=?",
        (nid, uid)
    ).fetchone()
    if not note:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    conn.execute("DELETE FROM book_notes WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Regale
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/shelves', methods=['POST'])
@login_required
def create_shelf():
    d = request.json
    uid = session['user_id']
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name erforderlich'}), 400
    conn = get_db()
    conn.execute("INSERT INTO shelves (user_id, name) VALUES (?,?)", (uid, name))
    shid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': shid, 'success': True})


@csrf.exempt
@app.route('/api/shelves/<int:shid>', methods=['PUT', 'DELETE'])
@login_required
def shelf_api(shid):
    uid = session['user_id']
    conn = get_db()
    if request.method == 'PUT':
        d = request.json
        conn.execute("UPDATE shelves SET name=? WHERE id=? AND user_id=?", ((d.get('name') or '').strip(), shid, uid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    conn.execute("DELETE FROM shelves WHERE id=? AND user_id=?", (shid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/shelves/<int:shid>/books', methods=['POST'])
@login_required
def add_to_shelf(shid):
    uid = session['user_id']
    d = request.json
    book_id = d.get('book_id')
    conn = get_db()
    shelf = conn.execute("SELECT id FROM shelves WHERE id=? AND user_id=?", (shid, uid)).fetchone()
    if not shelf:
        conn.close()
        return jsonify({'error': 'Shelf nicht gefunden'}), 404
    conn.execute("INSERT OR IGNORE INTO shelf_books (shelf_id, book_id) VALUES (?,?)", (shid, book_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/shelves/<int:shid>/books/<int:bid>', methods=['DELETE'])
@login_required
def remove_from_shelf(shid, bid):
    uid = session['user_id']
    conn = get_db()
    shelf = conn.execute("SELECT id FROM shelves WHERE id=? AND user_id=?", (shid, uid)).fetchone()
    if not shelf:
        conn.close()
        return jsonify({'error': 'Shelf nicht gefunden'}), 404
    conn.execute("DELETE FROM shelf_books WHERE shelf_id=? AND book_id=?", (shid, bid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Serien
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/series', methods=['GET', 'POST'])
@login_required
def series_api():
    uid = session['user_id']
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM series WHERE user_id=? ORDER BY name", (uid,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    d = request.json
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name erforderlich'}), 400
    conn.execute("INSERT OR IGNORE INTO series (user_id, name) VALUES (?,?)", (uid, name))
    row = conn.execute("SELECT id FROM series WHERE user_id=? AND name=?", (uid, name)).fetchone()
    conn.commit()
    conn.close()
    return jsonify({'id': row['id'], 'success': True})


@csrf.exempt
@app.route('/api/series/<int:sid>', methods=['DELETE'])
@login_required
def delete_series(sid):
    uid = session['user_id']
    conn = get_db()
    conn.execute("UPDATE books SET series_id=NULL, series_order=NULL WHERE series_id=? AND user_id=?", (sid, uid))
    conn.execute("DELETE FROM series WHERE id=? AND user_id=?", (sid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@csrf.exempt
@app.route('/api/books/<int:book_id>/series', methods=['PUT'])
@login_required
def assign_series(book_id):
    uid = session['user_id']
    d = request.json
    conn = get_db()
    book = conn.execute("SELECT id FROM books WHERE id=? AND user_id=?", (book_id, uid)).fetchone()
    if not book:
        conn.close()
        return jsonify({'error': 'Buch nicht gefunden'}), 404
    conn.execute(
        "UPDATE books SET series_id=?, series_order=? WHERE id=?",
        (d.get('series_id') or None, d.get('series_order') or None, book_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  API â€" Verliehen
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
@csrf.exempt
@app.route('/api/books/<int:book_id>/lent', methods=['PUT'])
@login_required
def update_lent(book_id):
    d = request.json
    conn = get_db()
    conn.execute(
        "UPDATE books SET lent_to=?, lent_date=? WHERE id=?",
        (d.get('lent_to') or None, d.get('lent_date') or None, book_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# ──────────────────────────────────────────────────────────────────
#  Admin Panel
# ──────────────────────────────────────────────────────────────────
@app.route('/api/admin/status')
@login_required
@admin_required
def admin_status_api():
    """Liefert Live-Daten für die Admin Status-Bar."""
    conn = get_db()
    total_users    = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
    active_users   = conn.execute(
        "SELECT COUNT(*) as c FROM users WHERE last_seen > datetime('now', '-15 minutes') AND is_active=1"
    ).fetchone()['c']
    open_reports   = conn.execute("SELECT COUNT(*) as c FROM reports WHERE status='open'").fetchone()['c']
    last_backup    = get_app_setting('last_backup', '')
    conn.close()
    return jsonify({
        'total_users':  total_users,
        'active_users': active_users,
        'open_reports': open_reports,
        'last_backup':  last_backup[:16] if last_backup else 'Noch kein Backup',
        'online':       True,
    })

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    conn = get_db()
    users = conn.execute(
        "SELECT id, username, email, email_verified, is_active, is_banned, is_admin, ad_enabled, created_at "
        "FROM users ORDER BY created_at DESC"
    ).fetchall()
    logs = conn.execute(
        "SELECT * FROM hacker_logs ORDER BY timestamp DESC LIMIT 300"
    ).fetchall()
    audit_logs = conn.execute(
        "SELECT al.*, u.username as admin_username FROM audit_logs al "
        "LEFT JOIN users u ON al.admin_id=u.id ORDER BY al.timestamp DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template('admin.html', users=users, logs=logs, audit_logs=audit_logs)

@csrf.exempt
@app.route('/admin/users/<int:uid>/activate', methods=['POST'])
@login_required
@admin_required
def admin_activate(uid):
    conn = get_db()
    conn.execute("UPDATE users SET is_active=1, is_banned=0, email_verified=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    log_audit('user_activated', uid)
    return jsonify({'success': True})

@csrf.exempt
@app.route('/admin/users/<int:uid>/ban', methods=['POST'])
@login_required
@admin_required
def admin_ban(uid):
    conn = get_db()
    conn.execute("UPDATE users SET is_banned=1, is_active=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    log_audit('user_banned', uid)
    return jsonify({'success': True})

@csrf.exempt
@app.route('/admin/users/<int:uid>/unban', methods=['POST'])
@login_required
@admin_required
def admin_unban(uid):
    conn = get_db()
    conn.execute("UPDATE users SET is_banned=0, is_active=1 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    log_audit('user_unbanned', uid)
    return jsonify({'success': True})

@csrf.exempt
@app.route('/admin/users/<int:uid>/toggle-ad', methods=['POST'])
@login_required
@admin_required
def admin_toggle_ad(uid):
    conn = get_db()
    row = conn.execute("SELECT ad_enabled FROM users WHERE id=?", (uid,)).fetchone()
    new_val = 0 if (row and row['ad_enabled']) else 1
    conn.execute("UPDATE users SET ad_enabled=? WHERE id=?", (new_val, uid))
    conn.commit()
    conn.close()
    log_audit('ad_toggled', uid, detail=f'ad_enabled={new_val}')
    return jsonify({'success': True, 'ad_enabled': new_val})

@csrf.exempt
@app.route('/admin/users/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(uid):
    """Löscht einen User und alle seine Daten. Admins sind geschützt."""
    current_uid = session['user_id']
    if uid == current_uid:
        return jsonify({'error': 'Du kannst deinen eigenen Account nicht löschen'}), 400
    conn = get_db()
    target = conn.execute("SELECT is_admin, username FROM users WHERE id=?", (uid,)).fetchone()
    if not target:
        conn.close()
        return jsonify({'error': 'Benutzer nicht gefunden'}), 404
    if target['is_admin']:
        conn.close()
        return jsonify({'error': 'Admin-Accounts können nicht gelöscht werden'}), 403

    # Alle Bücher des Users holen (für kaskadierende Löschung von Fortschritten etc.)
    book_ids = [r['id'] for r in conn.execute(
        "SELECT id FROM books WHERE user_id=?", (uid,)
    ).fetchall()]

    # Bücherabhängige Tabellen manuell löschen (falls kein CASCADE)
    for bid in book_ids:
        for tbl in ['reading_progress', 'audio_progress', 'ratings', 'reviews', 'quotes', 'book_notes']:
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE book_id=?", (bid,))
            except Exception:
                pass
        try:
            conn.execute("DELETE FROM shelf_books WHERE book_id=?", (bid,))
        except Exception:
            pass

    # Regale, die nur diesem User gehören, und ihre Einträge löschen
    shelf_ids = [r['id'] for r in conn.execute(
        "SELECT id FROM shelves WHERE user_id=?", (uid,)
    ).fetchall()]
    for sid in shelf_ids:
        conn.execute("DELETE FROM shelf_books WHERE shelf_id=?", (sid,))
    conn.execute("DELETE FROM shelves WHERE user_id=?", (uid,))

    # Serien des Users löschen
    conn.execute("DELETE FROM series WHERE user_id=?", (uid,))

    # Wunschliste löschen
    conn.execute("DELETE FROM wishlist WHERE user_id=?", (uid,))

    # Bücher löschen
    conn.execute("DELETE FROM books WHERE user_id=?", (uid,))

    # Leseziele, Einstellungen, Werbebanner löschen
    for tbl in ['reading_goals', 'user_settings', 'advertisements']:
        try:
            conn.execute(f"DELETE FROM {tbl} WHERE user_id=?", (uid,))
        except Exception:
            pass

    # User selbst löschen
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()

    log_audit('user_deleted', uid, target['username'], f'deleted_by={current_uid}')
    return jsonify({'success': True})

@csrf.exempt
@app.route('/admin/users/<int:uid>/details', methods=['GET'])
@login_required
@admin_required
def admin_user_details(uid):
    """Gibt detaillierte Informationen über einen User als JSON."""
    conn = get_db()
    user = conn.execute(
        "SELECT id, username, email, email_verified, is_active, is_banned, is_admin, ad_enabled, created_at "
        "FROM users WHERE id=?", (uid,)
    ).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    ips = conn.execute(
        "SELECT ip, timestamp FROM user_ips WHERE user_id=? ORDER BY timestamp DESC LIMIT 5",
        (uid,)
    ).fetchall()
    alogs = conn.execute(
        "SELECT action, detail, ip, timestamp FROM audit_logs WHERE target_user_id=? ORDER BY timestamp DESC LIMIT 20",
        (uid,)
    ).fetchall()
    conn.close()
    return jsonify({
        'user': dict(user),
        'ips': [dict(r) for r in ips],
        'audit': [dict(r) for r in alogs],
    })

@csrf.exempt
@app.route('/admin/impersonate/<int:uid>', methods=['POST'])
@login_required
@admin_required
def admin_impersonate(uid):
    """Admin personifiziert einen User."""
    conn = get_db()
    target = conn.execute("SELECT id, username, is_admin FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not target or target['is_admin']:
        return jsonify({'error': 'Nicht erlaubt'}), 403
    log_audit('impersonation_started', uid, target['username'])
    session['impersonated_by'] = session['user_id']
    session['impersonated_by_username'] = session['username']
    session['user_id'] = uid
    session['username'] = target['username']
    session['is_admin'] = False
    return jsonify({'success': True})

@app.route('/admin/stop-impersonation')
def stop_impersonation():
    """Beendet Impersonation."""
    if 'impersonated_by' not in session:
        return redirect(url_for('dashboard'))
    orig_id = session.pop('impersonated_by')
    orig_name = session.pop('impersonated_by_username', 'Admin')
    log_audit('impersonation_ended', session.get('user_id'), session.get('username'))
    session['user_id'] = orig_id
    session['username'] = orig_name
    session['is_admin'] = True
    return redirect(url_for('admin_panel'))

@csrf.exempt
@app.route('/admin/toggle-maintenance', methods=['POST'])
@login_required
@admin_required
def admin_toggle_maintenance():
    """Schaltet Wartungsmodus um."""
    current = get_app_setting('maintenance_mode', '0')
    new_val = '0' if current == '1' else '1'
    set_app_setting('maintenance_mode', new_val)
    log_audit('maintenance_toggled', detail=f'mode={new_val}')
    return jsonify({'success': True, 'maintenance': new_val == '1'})

@app.route('/maintenance')
def maintenance_page():
    """Zeigt die Wartungsseite."""
    if session.get('is_admin'):
        return redirect(url_for('dashboard'))
    return render_template('maintenance.html')

@csrf.exempt
@app.route('/admin/backup')
@login_required
@admin_required
def admin_backup():
    """Erstellt ein Backup und lädt es herunter."""
    try:
        zip_path = create_backup()
        log_audit('backup_created')
        with open(zip_path, 'rb') as f:
            return Response(
                f.read(),
                mimetype='application/zip',
                headers={'Content-Disposition': f'attachment; filename={os.path.basename(zip_path)}'}
            )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ──────────────────────────────────────────────────────────────────
#  Werbung (Advertisement)
# ──────────────────────────────────────────────────────────────────
@csrf.exempt
@app.route('/api/advertisement', methods=['GET', 'POST'])
@login_required
def advertisement_api():
    uid = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT ad_enabled FROM users WHERE id=?", (uid,)).fetchone()
    if not user or not user['ad_enabled']:
        conn.close()
        return jsonify({'error': 'Werbefunktion nicht aktiviert'}), 403
    if request.method == 'GET':
        ad = conn.execute("SELECT * FROM advertisements WHERE user_id=?", (uid,)).fetchone()
        conn.close()
        return jsonify(dict(ad) if ad else {})
    d = request.json or {}
    existing = conn.execute("SELECT id FROM advertisements WHERE user_id=?", (uid,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE advertisements SET logo_url=?, title=?, body_text=?, is_active=? WHERE user_id=?",
            (d.get('logo_url'), d.get('title'), d.get('body_text'),
             1 if d.get('is_active', True) else 0, uid)
        )
    else:
        conn.execute(
            "INSERT INTO advertisements (user_id, logo_url, title, body_text, is_active) VALUES (?,?,?,?,1)",
            (uid, d.get('logo_url'), d.get('title'), d.get('body_text'))
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@csrf.exempt
@app.route('/api/advertisement/toggle', methods=['POST'])
@login_required
def toggle_advertisement():
    uid = session['user_id']
    conn = get_db()
    ad = conn.execute("SELECT id, is_active FROM advertisements WHERE user_id=?", (uid,)).fetchone()
    if ad:
        new_val = 0 if ad['is_active'] else 1
        conn.execute("UPDATE advertisements SET is_active=? WHERE user_id=?", (new_val, uid))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'is_active': new_val})
    conn.close()
    return jsonify({'error': 'Keine Werbung gefunden'}), 404

@csrf.exempt
@app.route('/api/advertisement/logo', methods=['POST'])
@login_required
def upload_ad_logo():
    uid = session['user_id']
    conn = get_db()
    user = conn.execute("SELECT ad_enabled FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not user or not user['ad_enabled']:
        return jsonify({'error': 'Nicht erlaubt'}), 403
    if 'logo' not in request.files:
        return jsonify({'error': 'Keine Datei'}), 400
    f = request.files['logo']
    allowed = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'Ungültiger Dateityp'}), 400
    fname = f'ad_{uid}_{uuid.uuid4()}.{ext}'
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'ads')
    os.makedirs(upload_dir, exist_ok=True)
    f.save(os.path.join(upload_dir, fname))
    return jsonify({'url': f'/static/uploads/ads/{fname}'})


# ──────────────────────────────────────────────────────────────────────────────
#  CHAT SYSTEM
# ──────────────────────────────────────────────────────────────────────────────
CHAT_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'chat')
CHAT_MAX_SIZE   = 5 * 1024 * 1024   # 5 MB
CHAT_ALLOWED    = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

def _are_mutuals(conn, a, b):
    """True wenn a und b sich gegenseitig folgen."""
    ab = conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (a, b)).fetchone()
    ba = conn.execute("SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (b, a)).fetchone()
    return bool(ab and ba)

@app.route('/chat')
@login_required
def chat_overview():
    uid = session['user_id']
    conn = get_db()
    # Alle Mutuals (gegenseitiges Folgen)
    mutuals = conn.execute("""
        SELECT u.id, u.username,
               (SELECT content FROM chat_messages
                WHERE (sender_id=u.id AND receiver_id=?) OR (sender_id=? AND receiver_id=u.id)
                ORDER BY created_at DESC LIMIT 1) as last_msg,
               (SELECT created_at FROM chat_messages
                WHERE (sender_id=u.id AND receiver_id=?) OR (sender_id=? AND receiver_id=u.id)
                ORDER BY created_at DESC LIMIT 1) as last_time,
               (SELECT COUNT(*) FROM chat_messages
                WHERE sender_id=u.id AND receiver_id=? AND read_at IS NULL) as unread
        FROM users u
        WHERE u.id IN (SELECT followed_id FROM follows WHERE follower_id=?)
          AND u.id IN (SELECT follower_id FROM follows WHERE followed_id=?)
          AND u.is_active=1
        ORDER BY last_time DESC NULLS LAST
    """, (uid, uid, uid, uid, uid, uid, uid)).fetchall()
    conn.close()
    return render_template('chat.html', mutuals=mutuals)

@app.route('/chat/<username>')
@login_required
def chat_conversation(username):
    uid = session['user_id']
    conn = get_db()
    partner = conn.execute("SELECT id, username FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
    if not partner:
        conn.close(); abort(404)
    if not _are_mutuals(conn, uid, partner['id']):
        conn.close(); abort(403)
    # Letzte 40 Nachrichten
    msgs = conn.execute("""
        SELECT cm.*, u.username as sender_name
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE (cm.sender_id=? AND cm.receiver_id=?) OR (cm.sender_id=? AND cm.receiver_id=?)
        ORDER BY cm.created_at DESC LIMIT 40
    """, (uid, partner['id'], partner['id'], uid)).fetchall()
    msgs = list(reversed(msgs))
    # Als gelesen markieren
    conn.execute("""
        UPDATE chat_messages SET read_at=CURRENT_TIMESTAMP
        WHERE sender_id=? AND receiver_id=? AND read_at IS NULL
    """, (partner['id'], uid))
    conn.commit(); conn.close()
    return render_template('chat_conversation.html', partner=partner, msgs=msgs, uid=uid)

@csrf.exempt
@app.route('/api/chat/<int:partner_id>/messages')
@login_required
def chat_load_messages(partner_id):
    uid = session['user_id']
    before_id = request.args.get('before', type=int)
    conn = get_db()
    if not _are_mutuals(conn, uid, partner_id):
        conn.close(); return jsonify({'error': 'Nicht erlaubt'}), 403
    q = """SELECT cm.id, cm.sender_id, cm.content, cm.image_url, cm.created_at, u.username as sender_name
           FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
           WHERE ((cm.sender_id=? AND cm.receiver_id=?) OR (cm.sender_id=? AND cm.receiver_id=?))"""
    params = [uid, partner_id, partner_id, uid]
    if before_id:
        q += " AND cm.id < ?"
        params.append(before_id)
    q += " ORDER BY cm.created_at DESC LIMIT 30"
    msgs = conn.execute(q, params).fetchall()
    conn.close()
    return jsonify([dict(m) for m in reversed(msgs)])

@csrf.exempt
@app.route('/api/chat/<int:partner_id>/send', methods=['POST'])
@login_required
def chat_send(partner_id):
    uid = session['user_id']
    conn = get_db()
    if not _are_mutuals(conn, uid, partner_id):
        conn.close(); return jsonify({'error': 'Nicht erlaubt'}), 403
    image_url = None
    # Bild-Upload
    if 'image' in request.files:
        f = request.files['image']
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in CHAT_ALLOWED:
            conn.close(); return jsonify({'error': 'Nur JPG/PNG/GIF/WebP erlaubt'}), 400
        f.seek(0, 2); size = f.tell(); f.seek(0)
        if size > CHAT_MAX_SIZE:
            conn.close(); return jsonify({'error': 'Bild zu groß (max. 5 MB)'}), 400
        # Magic-Bytes prüfen
        header = f.read(12); f.seek(0)
        magic_ok = (header[:3] == b'\xff\xd8\xff' or header[:4] in (b'\x89PNG', b'GIF8', b'RIFF') or header[8:12] == b'WEBP')
        if not magic_ok:
            conn.close(); return jsonify({'error': 'Ungültiges Bildformat'}), 400
        os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)
        fname = f'chat_{uuid.uuid4()}.{ext}'
        f.save(os.path.join(CHAT_UPLOAD_DIR, fname))
        image_url = f'/static/uploads/chat/{fname}'
        content = request.form.get('content', '').strip()
    else:
        data = request.get_json() or {}
        content = (data.get('content') or '').strip()
    if not content and not image_url:
        conn.close(); return jsonify({'error': 'Leere Nachricht'}), 400
    if len(content) > 2000:
        conn.close(); return jsonify({'error': 'Nachricht zu lang (max. 2000 Zeichen)'}), 400
    conn.execute(
        "INSERT INTO chat_messages (sender_id, receiver_id, content, image_url) VALUES (?,?,?,?)",
        (uid, partner_id, content or None, image_url)
    )
    conn.commit()
    msg = conn.execute("""
        SELECT cm.id, cm.sender_id, cm.content, cm.image_url, cm.created_at, u.username as sender_name
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE cm.sender_id=? AND cm.receiver_id=? ORDER BY cm.created_at DESC LIMIT 1
    """, (uid, partner_id)).fetchone()
    conn.close()
    return jsonify({'success': True, 'msg': dict(msg)})

@csrf.exempt
@app.route('/api/chat/<int:partner_id>/poll')
@login_required
def chat_poll(partner_id):
    """Neue Nachrichten seit after_id (Long-Polling light)."""
    uid = session['user_id']
    after_id = request.args.get('after', 0, type=int)
    conn = get_db()
    msgs = conn.execute("""
        SELECT cm.id, cm.sender_id, cm.content, cm.image_url, cm.created_at, u.username as sender_name
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE ((cm.sender_id=? AND cm.receiver_id=?) OR (cm.sender_id=? AND cm.receiver_id=?))
          AND cm.id > ?
        ORDER BY cm.created_at ASC LIMIT 50
    """, (uid, partner_id, partner_id, uid, after_id)).fetchall()
    # Als gelesen markieren
    if msgs:
        conn.execute("""
            UPDATE chat_messages SET read_at=CURRENT_TIMESTAMP
            WHERE sender_id=? AND receiver_id=? AND read_at IS NULL
        """, (partner_id, uid))
        conn.commit()
    conn.close()
    return jsonify([dict(m) for m in msgs])

# Admin: Chat-Verlauf einsehen (nur bei gemeldeten Chats)
@app.route('/admin/chat-view/<int:uid1>/<int:uid2>')
@login_required
@admin_required
def admin_view_chat(uid1, uid2):
    # Prüfen ob es eine offene Meldung für diesen Chat gibt
    conn = get_db()
    report = conn.execute(
        "SELECT id FROM reports WHERE target_type='chat' AND status='open' AND "
        "((reporter_id=? AND target_id=?) OR (reporter_id=? AND target_id=?))",
        (uid1, uid2, uid2, uid1)
    ).fetchone()
    msgs = conn.execute("""
        SELECT cm.*, u.username as sender_name
        FROM chat_messages cm JOIN users u ON cm.sender_id=u.id
        WHERE (cm.sender_id=? AND cm.receiver_id=?) OR (cm.sender_id=? AND cm.receiver_id=?)
        ORDER BY cm.created_at ASC LIMIT 200
    """, (uid1, uid2, uid2, uid1)).fetchall()
    u1 = conn.execute("SELECT username FROM users WHERE id=?", (uid1,)).fetchone()
    u2 = conn.execute("SELECT username FROM users WHERE id=?", (uid2,)).fetchone()
    conn.close()
    # Audit-Log
    log_audit('admin_view_chat', uid1, u1['username'] if u1 else '?',
              f'Chatprotokoll mit User {uid2} eingesehen (Report: {"ja" if report else "kein offener Report"})')
    return render_template('admin_chat_view.html', msgs=msgs, u1=u1, u2=u2, uid1=uid1, uid2=uid2)

# ──────────────────────────────────────────────────────────────────────────────
#  REPORT SYSTEM
# ──────────────────────────────────────────────────────────────────────────────
REPORT_REASONS = ['Spam', 'Beleidigung / Hassrede', 'Unangemessene Bilder', 'Betrug / Fake', 'Urheberrechtsverletzung', 'Anderes']

@csrf.exempt
@app.route('/api/report', methods=['POST'])
@login_required
def submit_report():
    uid = session['user_id']
    data = request.get_json() or {}
    target_id   = data.get('target_id')
    target_type = data.get('target_type', '')   # profile, chat, post, message
    reason      = data.get('reason', '').strip()
    detail      = data.get('detail', '').strip()[:500]
    if not target_type or not reason:
        return jsonify({'error': 'Fehlende Felder'}), 400
    if reason not in REPORT_REASONS:
        return jsonify({'error': 'Ungültiger Grund'}), 400
    conn = get_db()
    # Doppel-Meldung verhindern (gleicher Reporter+Target in 24h)
    existing = conn.execute(
        "SELECT id FROM reports WHERE reporter_id=? AND target_id=? AND target_type=? AND created_at > datetime('now','-1 day')",
        (uid, target_id, target_type)
    ).fetchone()
    if existing:
        conn.close(); return jsonify({'error': 'Du hast das bereits gemeldet'}), 409
    conn.execute(
        "INSERT INTO reports (reporter_id, target_id, target_type, reason, detail) VALUES (?,?,?,?,?)",
        (uid, target_id, target_type, reason, detail)
    )
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    status_filter = request.args.get('status', 'open')
    conn = get_db()
    reports = conn.execute("""
        SELECT r.*, u1.username as reporter_name, u2.username as target_username
        FROM reports r
        JOIN users u1 ON r.reporter_id=u1.id
        LEFT JOIN users u2 ON r.target_id=u2.id AND r.target_type='profile'
        WHERE r.status=?
        ORDER BY r.created_at DESC LIMIT 100
    """, (status_filter,)).fetchall()
    open_count   = conn.execute("SELECT COUNT(*) as c FROM reports WHERE status='open'").fetchone()['c']
    closed_count = conn.execute("SELECT COUNT(*) as c FROM reports WHERE status!='open'").fetchone()['c']
    conn.close()
    return render_template('admin_reports.html', reports=reports, status_filter=status_filter,
                           open_count=open_count, closed_count=closed_count)

@csrf.exempt
@app.route('/api/admin/report/<int:report_id>/action', methods=['POST'])
@login_required
@admin_required
def admin_report_action(report_id):
    data = request.get_json() or {}
    action = data.get('action')   # dismiss, delete_content, warn_user, ban_user
    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not report:
        conn.close(); return jsonify({'error': 'Report nicht gefunden'}), 404

    admin_id = session['user_id']
    admin_name = session.get('username', 'Admin')

    if action == 'dismiss':
        conn.execute("UPDATE reports SET status='dismissed', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (admin_id, report_id))
        log_audit('report_dismissed', report['reporter_id'], str(report['reporter_id']),
                  f'Report #{report_id} ({report["target_type"]}) abgewiesen')

    elif action == 'warn_user' and report['target_id']:
        reason_text = f"Gemeldet wegen: {report['reason']}"
        conn.execute("INSERT INTO user_warnings (user_id, admin_id, reason) VALUES (?,?,?)",
                     (report['target_id'], admin_id, reason_text))
        conn.execute("UPDATE reports SET status='actioned', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (admin_id, report_id))
        target_user = conn.execute("SELECT username FROM users WHERE id=?", (report['target_id'],)).fetchone()
        log_audit('user_warned', report['target_id'],
                  target_user['username'] if target_user else '?',
                  f'Verwarnung via Report #{report_id}: {report["reason"]}')

    elif action == 'ban_user' and report['target_id']:
        conn.execute("UPDATE users SET is_banned=1 WHERE id=?", (report['target_id'],))
        conn.execute("UPDATE reports SET status='actioned', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (admin_id, report_id))
        target_user = conn.execute("SELECT username FROM users WHERE id=?", (report['target_id'],)).fetchone()
        log_audit('user_banned', report['target_id'],
                  target_user['username'] if target_user else '?',
                  f'Gesperrt via Report #{report_id}: {report["reason"]}')

    elif action == 'delete_content':
        # Chat-Bild löschen
        if report['target_type'] == 'chat_image' and report['target_id']:
            msg = conn.execute("SELECT image_url FROM chat_messages WHERE id=?", (report['target_id'],)).fetchone()
            if msg and msg['image_url']:
                img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), msg['image_url'].lstrip('/'))
                try: os.remove(img_path)
                except: pass
            conn.execute("UPDATE chat_messages SET image_url=NULL, content='[Inhalt gelöscht]' WHERE id=?",
                         (report['target_id'],))
        # Community-Post löschen
        elif report['target_type'] == 'post' and report['target_id']:
            conn.execute("DELETE FROM community_posts WHERE id=?", (report['target_id'],))
        # Chat-Nachricht löschen
        elif report['target_type'] == 'message' and report['target_id']:
            conn.execute("UPDATE chat_messages SET content='[Inhalt gelöscht]', image_url=NULL WHERE id=?",
                         (report['target_id'],))
        conn.execute("UPDATE reports SET status='actioned', resolved_by=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                     (admin_id, report_id))
        log_audit('content_deleted', report['reporter_id'], str(report['reporter_id']),
                  f'Inhalt gelöscht via Report #{report_id}')
    else:
        conn.close(); return jsonify({'error': 'Unbekannte Aktion'}), 400

    conn.commit(); conn.close()
    return jsonify({'success': True})

# ──────────────────────────────────────────────────────────────────────────────
#  COMMUNITY FEED
# ──────────────────────────────────────────────────────────────────────────────
@app.route('/community')
@login_required
def community():
    uid = session['user_id']
    conn = get_db()
    year  = datetime.now(timezone.utc).year
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    stats = {}
    stats['total_books']       = conn.execute("SELECT COUNT(*) as c FROM books").fetchone()['c']
    stats['total_users']       = conn.execute("SELECT COUNT(*) as c FROM users WHERE is_active=1").fetchone()['c']
    stats['books_this_month']  = conn.execute(
        "SELECT COUNT(*) as c FROM books WHERE strftime('%Y-%m', read_date)=?", (month,)).fetchone()['c']
    stats['pages_this_month']  = conn.execute(
        "SELECT COALESCE(SUM(pages),0) as s FROM books WHERE strftime('%Y-%m', read_date)=?", (month,)).fetchone()['s']
    genres = conn.execute(
        "SELECT genre, COUNT(*) as cnt FROM books WHERE genre IS NOT NULL AND genre!='' "
        "GROUP BY genre ORDER BY cnt DESC LIMIT 10").fetchall()
    # Community-Feed: Posts von allen Usern mit öffentlichem Profil (neueste zuerst)
    feed = conn.execute("""
        SELECT cp.id, cp.content, cp.book_title, cp.book_cover, cp.post_type, cp.created_at,
               u.username, u.id as author_id,
               (SELECT COUNT(*) FROM post_likes pl WHERE pl.post_id=cp.id) as like_count,
               (SELECT 1 FROM post_likes pl WHERE pl.post_id=cp.id AND pl.user_id=?) as liked
        FROM community_posts cp
        JOIN users u ON cp.user_id=u.id
        WHERE u.is_active=1
        ORDER BY cp.created_at DESC LIMIT 30
    """, (uid,)).fetchall()
    # Buddy-Vorschläge: User mit gleichen Genres (noch nicht gefolgt)
    my_genres = conn.execute(
        "SELECT genre, COUNT(*) as cnt FROM books WHERE user_id=? AND genre IS NOT NULL AND genre!='' "
        "GROUP BY genre ORDER BY cnt DESC LIMIT 5", (uid,)
    ).fetchall()
    buddy_suggestions = []
    if my_genres:
        genre_list = [g['genre'] for g in my_genres]
        placeholders = ','.join('?' * len(genre_list))
        buddy_suggestions = conn.execute(f"""
            SELECT u.id, u.username, COUNT(*) as match_count,
                   GROUP_CONCAT(DISTINCT b.genre) as common_genres
            FROM users u
            JOIN books b ON b.user_id=u.id AND b.genre IN ({placeholders})
            WHERE u.id!=? AND u.is_active=1
              AND u.id NOT IN (SELECT followed_id FROM follows WHERE follower_id=?)
            GROUP BY u.id ORDER BY match_count DESC LIMIT 6
        """, genre_list + [uid, uid]).fetchall()
    # Fallback: wenn keine Genre-Übereinstimmung, zeige aktive User die man noch nicht folgt
    if not buddy_suggestions:
        buddy_suggestions = conn.execute("""
            SELECT u.id, u.username, 0 as match_count, '' as common_genres
            FROM users u
            WHERE u.id!=? AND u.is_active=1
              AND u.id NOT IN (SELECT followed_id FROM follows WHERE follower_id=?)
            ORDER BY RANDOM() LIMIT 6
        """, (uid, uid)).fetchall()
    conn.close()
    return render_template('community.html',
        stats=stats, genres=genres, feed=feed,
        buddy_suggestions=buddy_suggestions, uid=uid)

@app.route('/api/community/search-users')
@login_required
def community_search_users():
    """Live-Suche nach Usern für Community-Dropdown."""
    uid = session['user_id']
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username FROM users "
        "WHERE username LIKE ? AND is_active=1 AND id!=? LIMIT 8",
        (f'%{q}%', uid)
    ).fetchall()
    conn.close()
    return jsonify([{'id': r['id'], 'username': r['username']} for r in rows])


@csrf.exempt
@app.route('/api/community/post', methods=['POST'])
@login_required
def community_post_create():
    uid = session['user_id']
    data = request.get_json() or {}
    content    = (data.get('content') or '').strip()
    book_title = (data.get('book_title') or '').strip()
    book_cover = (data.get('book_cover') or '').strip()
    post_type  = data.get('post_type', 'review')
    if not content or len(content) < 3:
        return jsonify({'error': 'Beitrag zu kurz'}), 400
    if len(content) > 1000:
        return jsonify({'error': 'Max. 1000 Zeichen'}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO community_posts (user_id, book_title, book_cover, content, post_type) VALUES (?,?,?,?,?)",
        (uid, book_title or None, book_cover or None, content, post_type)
    )
    conn.commit(); conn.close()
    return jsonify({'success': True})

@csrf.exempt
@app.route('/api/community/like/<int:post_id>', methods=['POST'])
@login_required
def community_like(post_id):
    uid = session['user_id']
    conn = get_db()
    existing = conn.execute("SELECT 1 FROM post_likes WHERE post_id=? AND user_id=?", (post_id, uid)).fetchone()
    if existing:
        conn.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?", (post_id, uid))
        liked = False
    else:
        conn.execute("INSERT INTO post_likes (post_id, user_id) VALUES (?,?)", (post_id, uid))
        liked = True
    count = conn.execute("SELECT COUNT(*) as c FROM post_likes WHERE post_id=?", (post_id,)).fetchone()['c']
    conn.commit(); conn.close()
    return jsonify({'success': True, 'liked': liked, 'count': count})

@csrf.exempt
@app.route('/api/community/post/<int:post_id>', methods=['DELETE'])
@login_required
def community_post_delete(post_id):
    uid = session['user_id']
    conn = get_db()
    post = conn.execute("SELECT user_id FROM community_posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        conn.close(); return jsonify({'error': 'Nicht gefunden'}), 404
    if post['user_id'] != uid and not session.get('is_admin'):
        conn.close(); return jsonify({'error': 'Nicht erlaubt'}), 403
    conn.execute("DELETE FROM community_posts WHERE id=?", (post_id,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ──────────────────────────────────────────────────────────────────
#  Error Handlers
# ──────────────────────────────────────────────────────────────────
@app.errorhandler(403)
def forbidden(e):
    log_hacker('403 Forbidden')
    return render_template('error.html', code=403, message='Zugriff verweigert'), 403

@app.errorhandler(404)
def not_found(e):
    log_hacker('404 Not Found')
    return render_template('error.html', code=404, message='Seite nicht gefunden'), 404

@app.errorhandler(405)
def method_not_allowed(e):
    log_hacker('405 Method Not Allowed',
               str(request.form.to_dict() or request.get_data(as_text=True)[:500]))
    return render_template('error.html', code=405, message='Methode nicht erlaubt'), 405

@app.errorhandler(429)
def rate_limited(e):
    log_hacker('429 Rate Limit')
    return render_template('error.html', code=429, message='Zu viele Anfragen. Bitte warte kurz.'), 429

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='Etwas ist schiefgelaufen'), 500


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  PWA Icons (generated at runtime)
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def make_png(size):
    """Generate a simple book-themed PNG icon."""
    w = h = size
    raw = b''
    for y in range(h):
        raw += b'\x00'
        for x in range(w):
            bx1, bx2 = int(0.18 * w), int(0.82 * w)
            by1, by2 = int(0.12 * h), int(0.88 * h)
            spine_x = int(0.32 * w)
            if bx1 < x < bx2 and by1 < y < by2:
                if abs(x - spine_x) <= max(1, w // 80):
                    raw += bytes([180, 190, 220])
                elif x < spine_x:
                    raw += bytes([96, 165, 250])
                else:
                    raw += bytes([248, 250, 252])
            else:
                raw += bytes([15, 23, 42])

    compressed = zlib.compress(raw)

    def chunk(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', ihdr)
    png += chunk(b'IDAT', compressed)
    png += chunk(b'IEND', b'')
    return png


@app.route('/icon-<int:size>x<int:size2>.png')
def serve_icon(size, size2):
    valid = {192: 'icon-192x192.png', 512: 'icon-512x512.png'}
    filename = valid.get(size, 'icon-192x192.png')
    return send_from_directory('static', filename)


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
#  DB Init
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS authors (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            UNIQUE(user_id, name)
        );
        CREATE TABLE IF NOT EXISTS publishers (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            UNIQUE(user_id, name)
        );
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL,
            publisher_id INTEGER REFERENCES publishers(id) ON DELETE SET NULL,
            isbn TEXT,
            cover_url TEXT,
            genre TEXT,
            pages INTEGER DEFAULT 0,
            format TEXT DEFAULT 'Paperback',
            release_date TEXT,
            series TEXT,
            volume TEXT,
            status TEXT DEFAULT 'Ungelesen',
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read_date TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author_id INTEGER REFERENCES authors(id) ON DELETE SET NULL,
            publisher_id INTEGER REFERENCES publishers(id) ON DELETE SET NULL,
            isbn TEXT,
            cover_url TEXT,
            genre TEXT,
            pages INTEGER DEFAULT 0,
            release_date TEXT,
            series TEXT,
            volume TEXT,
            status TEXT DEFAULT 'Ungelesen',
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reading_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            page INTEGER NOT NULL,
            delta INTEGER NOT NULL DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL UNIQUE REFERENCES books(id) ON DELETE CASCADE,
            stars INTEGER DEFAULT 0,
            spice INTEGER DEFAULT 0,
            tension INTEGER DEFAULT 0,
            type TEXT DEFAULT 'Fiction'
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL UNIQUE REFERENCES books(id) ON DELETE CASCADE,
            content TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            quote_text TEXT NOT NULL,
            page INTEGER,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reading_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_type TEXT NOT NULL,
            period TEXT NOT NULL,
            target INTEGER NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS shelves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS shelf_books (
            shelf_id INTEGER NOT NULL REFERENCES shelves(id) ON DELETE CASCADE,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            PRIMARY KEY (shelf_id, book_id)
        );
        CREATE TABLE IF NOT EXISTS book_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            chapter TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audio_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            percent INTEGER NOT NULL DEFAULT 0,
            delta INTEGER DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            email_verified INTEGER DEFAULT 0,
            verification_token TEXT,
            token_expires_at TEXT,
            is_active INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            totp_secret TEXT,
            totp_enabled INTEGER DEFAULT 0,
            ad_enabled INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS hacker_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT,
            user_agent TEXT,
            payload TEXT,
            path TEXT,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            target_user_id INTEGER,
            target_username TEXT,
            detail TEXT,
            ip TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            ip TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS notification_prefs (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            pref_key TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, pref_key)
        );
        CREATE TABLE IF NOT EXISTS advertisements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            logo_url TEXT,
            title TEXT,
            body_text TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        );
        CREATE TABLE IF NOT EXISTS follows (
            follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            followed_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (follower_id, followed_id)
        );
        CREATE TABLE IF NOT EXISTS buddy_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            partner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            book_title TEXT NOT NULL,
            book_cover TEXT,
            status TEXT DEFAULT 'pending',
            initiator_page INTEGER DEFAULT 0,
            partner_page INTEGER DEFAULT 0,
            total_pages INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS buddy_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buddy_read_id INTEGER NOT NULL REFERENCES buddy_reads(id) ON DELETE CASCADE,
            sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            is_spoiler INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS buddy_milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buddy_read_id INTEGER NOT NULL REFERENCES buddy_reads(id) ON DELETE CASCADE,
            creator_id INTEGER NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            target_page INTEGER,
            completed_by_initiator INTEGER DEFAULT 0,
            completed_by_partner INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content     TEXT,
            image_url   TEXT,
            read_at     TIMESTAMP,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            target_id    INTEGER,
            target_type  TEXT NOT NULL,
            reason       TEXT NOT NULL,
            detail       TEXT,
            status       TEXT DEFAULT 'open',
            resolved_by  INTEGER REFERENCES users(id),
            resolved_at  TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS community_posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            book_id    INTEGER REFERENCES books(id) ON DELETE SET NULL,
            book_title TEXT,
            book_cover TEXT,
            content    TEXT NOT NULL,
            post_type  TEXT DEFAULT 'review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS post_likes (
            post_id  INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
            user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS user_warnings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            admin_id   INTEGER NOT NULL REFERENCES users(id),
            reason     TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS support_tickets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            subject    TEXT NOT NULL,
            message    TEXT NOT NULL,
            category   TEXT DEFAULT 'general',
            status     TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS support_replies (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id  INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
            sender_id  INTEGER NOT NULL REFERENCES users(id),
            is_admin   INTEGER DEFAULT 0,
            message    TEXT NOT NULL,
            read_at    TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Migrations: neue Spalten zu bestehenden Tabellen hinzufügen
    # last_seen für User-Aktivität
    try:
        conn.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP")
    except Exception:
        pass

    for col_def in [
        ('lent_to', 'TEXT'),
        ('lent_date', 'TEXT'),
        ('series_id', 'INTEGER'),
        ('series_order', 'INTEGER'),
        ('is_audiobook', 'INTEGER DEFAULT 0'),
    ]:
        try:
            conn.execute(f"ALTER TABLE books ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass
    for col_def in [
        ('is_audiobook', 'INTEGER DEFAULT 0'),
    ]:
        try:
            conn.execute(f"ALTER TABLE wishlist ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass

    # user_id Spalte zu bestehenden Tabellen hinzufügen
    for table in ['books', 'wishlist', 'series', 'shelves', 'reading_goals']:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)")
        except Exception:
            pass

    # Reset-Token Spalten für Passwort-Reset hinzufügen
    for col_def in [
        ('reset_token', 'TEXT'),
        ('reset_token_expires_at', 'TEXT'),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass

    # ── authors / publishers: per-User-Migration ─────────────────────────────
    # Prüfe ob die alte globale UNIQUE(name)-Beschränkung noch aktiv ist.
    # Erkennungsmerkmal: schema enthält "name TEXT NOT NULL UNIQUE" als Inline-Constraint
    # OHNE eine zusammengesetzte UNIQUE(user_id, name)-Tabellen-Constraint.
    import re as _re
    for tbl in ('authors', 'publishers'):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
        ).fetchone()
        sql_def = (row['sql'] or '') if row else ''
        # Standalone UNIQUE auf name-Spalte (nicht composite)
        has_inline_unique   = bool(_re.search(r'name\s+TEXT[^,)]*UNIQUE', sql_def, _re.IGNORECASE))
        has_composite_unique = bool(_re.search(r'UNIQUE\s*\(\s*user_id', sql_def, _re.IGNORECASE))
        needs_rebuild = has_inline_unique and not has_composite_unique

        if needs_rebuild:
            # user_id-Spalte ggf. erst hinzufügen, bevor wir kopieren
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER REFERENCES users(id)")
            except Exception:
                pass
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(f"DROP TABLE IF EXISTS {tbl}_new")
            conn.execute(f"""
                CREATE TABLE {tbl}_new (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT NOT NULL,
                    user_id INTEGER REFERENCES users(id),
                    UNIQUE(user_id, name)
                )""")
            conn.execute(f"INSERT OR IGNORE INTO {tbl}_new (id, name, user_id) SELECT id, name, user_id FROM {tbl}")
            conn.execute(f"DROP TABLE {tbl}")
            conn.execute(f"ALTER TABLE {tbl}_new RENAME TO {tbl}")
            conn.execute("PRAGMA foreign_keys=ON")
        else:
            # Tabelle bereits korrekt – user_id-Spalte nur hinzufügen falls fehlend
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER REFERENCES users(id)")
            except Exception:
                pass

    conn.commit()

    # Composite-Unique-Indizes sicherstellen (nach Tabellen-Rebuild)
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_authors_user_name    ON authors(user_id, name)")
    except Exception:
        pass
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_publishers_user_name ON publishers(user_id, name)")
    except Exception:
        pass

    # Admin-User aus .env erstellen
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_email    = os.environ.get('ADMIN_EMAIL', 'admin@example.com')
    admin_password = os.environ.get('ADMIN_PASSWORD', '')
    if admin_password:
        existing = conn.execute(
            "SELECT id FROM users WHERE username=? OR email=?", (admin_username, admin_email)
        ).fetchone()
        if not existing:
            pw_hash = hash_pw(admin_password)
            conn.execute(
                "INSERT INTO users (username, email, password_hash, email_verified, is_active, is_admin) "
                "VALUES (?,?,?,1,1,1)",
                (admin_username, admin_email, pw_hash)
            )
            conn.commit()
        else:
            conn.execute(
                "UPDATE users SET is_admin=1, is_active=1, email_verified=1 WHERE id=?",
                (existing['id'],)
            )
            conn.commit()

    # Bestehende Daten dem Admin-User zuweisen (Migration von Single-User)
    admin_row = conn.execute("SELECT id FROM users WHERE is_admin=1 LIMIT 1").fetchone()
    if admin_row:
        admin_id = admin_row['id']
        for table in ['books', 'wishlist', 'series', 'shelves', 'reading_goals']:
            try:
                conn.execute(f"UPDATE {table} SET user_id=? WHERE user_id IS NULL", (admin_id,))
            except Exception:
                pass
        # authors/publishers: anhand der tatsächlich referenzierenden Bücher zuweisen
        try:
            conn.execute("""
                UPDATE authors SET user_id = (
                    SELECT b.user_id FROM books b WHERE b.author_id = authors.id LIMIT 1
                ) WHERE user_id IS NULL
            """)
        except Exception:
            pass
        try:
            conn.execute("""
                UPDATE publishers SET user_id = (
                    SELECT b.user_id FROM books b WHERE b.publisher_id = publishers.id LIMIT 1
                ) WHERE user_id IS NULL
            """)
        except Exception:
            pass
        # Alles was noch NULL ist (kein Buch verlinkt) → Admin
        try:
            conn.execute("UPDATE authors    SET user_id=? WHERE user_id IS NULL", (admin_id,))
        except Exception:
            pass
        try:
            conn.execute("UPDATE publishers SET user_id=? WHERE user_id IS NULL", (admin_id,))
        except Exception:
            pass
        conn.commit()

    defaults = [
        ('dark_mode', 'false'), ('show_reviews', 'true'),
        ('show_reviews', 'true'),
        ('show_statistics', 'true'),
        ('show_goals', 'true'),
        ('items_per_page', '12'),
    ]
    for key, default_val in defaults:
        existing = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?)", (key, default_val))
    conn.commit()

    # App Settings initialisieren
    try:
        conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('maintenance_mode', '0')")
        conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('last_backup', '')")
        conn.commit()
    except Exception:
        pass

    # public_profile default für bestehende User
    try:
        conn.execute("INSERT OR IGNORE INTO user_settings (user_id, key, value) SELECT id, 'public_profile', 'false' FROM users")
        conn.commit()
    except Exception:
        pass

    conn.close()


# ──────────────────────────────────────────────────────────────────
#  App Start
# ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=7443)
