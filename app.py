import subprocess
import sys

# Auto-install fehlende Pakete
def _ensure_packages():
    import importlib
    required = {'flask': 'Flask==3.0.3', 'requests': 'requests==2.31.0'}
    for module, pkg in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])

_ensure_packages()

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, Response, make_response)
import sqlite3
import os
import requests
import json
import csv
import io
from datetime import datetime, timedelta, timezone
from functools import wraps
import struct
import zlib
import uuid

app = Flask(__name__)
app.secret_key = 'rd_s3cr3t_2024_xK9p#mN2vL5_reading_diary'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=36500)

DEFAULT_PASSWORD = "admin"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reading_diary.db')


@app.after_request
def no_cache(response):
    """Verhindert Caching durch Nginx und Browser fÃ¼r HTML-Seiten."""
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Accel-Expires'] = '0'          # nginx proxy_cache deaktivieren
        response.headers['Surrogate-Control'] = 'no-store'  # CDN/Proxy-Cache deaktivieren
    return response


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  DB helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_setting(conn, key, default=''):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row['value'] if row else default


def upsert_author(conn, name):
    if not name or not name.strip():
        return None
    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO authors (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM authors WHERE name=?", (name,)).fetchone()
    return row['id'] if row else None


def upsert_publisher(conn, name):
    if not name or not name.strip():
        return None
    name = name.strip()
    conn.execute("INSERT OR IGNORE INTO publishers (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM publishers WHERE name=?", (name,)).fetchone()
    return row['id'] if row else None


def get_active_goal(conn):
    row = conn.execute(
        "SELECT * FROM reading_goals WHERE enabled=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def goal_progress(conn, goal):
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
            "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as total "
            "FROM reading_progress WHERE timestamp >= ?",
            (start.isoformat(),)
        ).fetchone()
        current = row['total']
    else:
        row = conn.execute(
            "SELECT COUNT(*) as total FROM books WHERE status='Gelesen' AND read_date >= ?",
            (start.isoformat(),)
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


def reading_streak(conn):
    """Berechnet aktuelle Lesesträhne in Tagen.
    Gilt auch noch am heutigen Tag, wenn gestern gelesen wurde."""
    rows = conn.execute(
        "SELECT DISTINCT DATE(timestamp) as d FROM reading_progress ORDER BY d DESC"
    ).fetchall()
    if not rows:
        return 0
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    first = datetime.strptime(rows[0]['d'], '%Y-%m-%d').date()
    # Strähne gilt, wenn heute ODER gestern zuletzt gelesen wurde
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


def max_reading_streak(conn):
    """Berechnet die höchste jemals erreichte Lesesträhne."""
    rows = conn.execute(
        "SELECT DISTINCT DATE(timestamp) as d FROM reading_progress ORDER BY d ASC"
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Auth
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def login_required(f):
    @wraps(f)
    def deco(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return deco


@app.context_processor
def inject_globals():
    if not session.get('logged_in'):
        return {}
    try:
        conn = get_db()
        dark_mode = get_setting(conn, 'dark_mode', 'false') == 'true'
        show_reviews = get_setting(conn, 'show_reviews', 'true') == 'true'
        show_stars   = get_setting(conn, 'show_stars',   'true') == 'true'
        show_spice   = get_setting(conn, 'show_spice',   'true') == 'true'
        show_tension = get_setting(conn, 'show_tension', 'true') == 'true'
        show_fiction = get_setting(conn, 'show_fiction', 'true') == 'true'
        show_lent      = get_setting(conn, 'show_lent',      'true') == 'true'
        show_streak    = get_setting(conn, 'show_streak',    'true') == 'true'
        show_audiobook = get_setting(conn, 'show_audiobook', 'true') == 'true'
        goal = get_active_goal(conn)
        progress = goal_progress(conn, goal)
        streak = reading_streak(conn)
        conn.close()
        return {
            'dark_mode': dark_mode,
            'show_reviews': show_reviews,
            'show_stars': show_stars,
            'show_spice': show_spice,
            'show_tension': show_tension,
            'show_fiction': show_fiction,
            'show_lent': show_lent,
            'show_streak': show_streak,
            'show_audiobook': show_audiobook,
            'goal': goal,
            'goal_progress': progress,
            'streak': streak,
        }
    except Exception:
        return {}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Page routes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        conn = get_db()
        stored_pw = get_setting(conn, 'password', DEFAULT_PASSWORD)
        conn.close()
        if pw == stored_pw:
            session.permanent = True
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = 'Falsches Passwort!'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    total_books = conn.execute("SELECT COUNT(*) as c FROM books").fetchone()['c']
    read_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE status='Gelesen'").fetchone()['c']
    total_quotes = conn.execute("SELECT COUNT(*) as c FROM quotes").fetchone()['c']
    reading = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.status='Am Lesen' ORDER BY b.added_date DESC"
    ).fetchall()
    recent = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.status != 'Am Lesen' ORDER BY b.added_date DESC LIMIT 8"
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
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        books_list = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id "
            "WHERE b.title LIKE ? OR a.name LIKE ? OR b.isbn LIKE ? "
            "ORDER BY b.added_date DESC",
            (f'%{q}%', f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        books_list = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id "
            "ORDER BY b.added_date DESC"
        ).fetchall()
    all_series = conn.execute("SELECT * FROM series ORDER BY name").fetchall()
    all_shelves = conn.execute("SELECT * FROM shelves ORDER BY name").fetchall()
    conn.close()
    return render_template('books.html', books=books_list, q=q,
                           all_series=all_series, all_shelves=all_shelves)


@app.route('/books/<int:book_id>')
@login_required
def book_detail(book_id):
    conn = get_db()
    book = conn.execute(
        "SELECT b.*, a.name as author_name, p.name as publisher_name, "
        "s.name as series_group_name "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id "
        "LEFT JOIN series s ON s.id=b.series_id "
        "WHERE b.id=?",
        (book_id,)
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

    rating = conn.execute("SELECT * FROM ratings WHERE book_id=?", (book_id,)).fetchone()
    review = conn.execute("SELECT * FROM reviews WHERE book_id=?", (book_id,)).fetchone()
    notes = conn.execute(
        "SELECT * FROM book_notes WHERE book_id=? ORDER BY created_at ASC", (book_id,)
    ).fetchall()
    all_series = conn.execute("SELECT * FROM series ORDER BY name").fetchall()
    show_reviews = get_setting(conn, 'show_reviews', 'true') == 'true'
    conn.close()

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
                           show_reviews=show_reviews)


@app.route('/wishlist')
@login_required
def wishlist():
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        items = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id "
            "WHERE w.title LIKE ? OR a.name LIKE ? ORDER BY w.added_date DESC",
            (f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        items = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id "
            "ORDER BY w.added_date DESC"
        ).fetchall()
    conn.close()
    return render_template('wishlist.html', items=items, q=q)


@app.route('/quotes')
@login_required
def quotes():
    conn = get_db()
    q = request.args.get('q', '')
    if q:
        quotes_list = conn.execute(
            "SELECT qt.*, b.title as book_title, a.name as author_name "
            "FROM quotes qt JOIN books b ON qt.book_id=b.id "
            "LEFT JOIN authors a ON b.author_id=a.id "
            "WHERE qt.quote_text LIKE ? OR b.title LIKE ? ORDER BY qt.added_date DESC",
            (f'%{q}%', f'%{q}%')
        ).fetchall()
    else:
        quotes_list = conn.execute(
            "SELECT qt.*, b.title as book_title, a.name as author_name "
            "FROM quotes qt JOIN books b ON qt.book_id=b.id "
            "LEFT JOIN authors a ON b.author_id=a.id ORDER BY qt.added_date DESC"
        ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id ORDER BY b.title"
    ).fetchall()
    conn.close()
    return render_template('quotes.html', quotes=quotes_list, books=all_books, q=q)


@app.route('/statistics')
@login_required
def statistics():
    conn = get_db()
    skeys = ['show_stats_total', 'show_stats_publishers', 'show_stats_authors', 'show_stats_graphs']
    stats_settings = {k: get_setting(conn, k, 'true') == 'true' for k in skeys}

    total_books = conn.execute("SELECT COUNT(*) as c FROM books").fetchone()['c']
    read_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE status='Gelesen'").fetchone()['c']
    unread_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE status='Ungelesen'").fetchone()['c']
    reading_books = conn.execute("SELECT COUNT(*) as c FROM books WHERE status='Am Lesen'").fetchone()['c']
    total_pages = conn.execute(
        "SELECT COALESCE((SELECT SUM(CASE WHEN delta>0 THEN delta ELSE 0 END) FROM reading_progress), 0)"
        " + COALESCE((SELECT SUM(b.pages) FROM books b WHERE b.status='Gelesen' AND COALESCE(b.pages,0)>0"
        "   AND NOT EXISTS (SELECT 1 FROM reading_progress rp WHERE rp.book_id=b.id)), 0) as t"
    ).fetchone()['t']
    total_quotes = conn.execute("SELECT COUNT(*) as c FROM quotes").fetchone()['c']
    publishers_stats = conn.execute(
        "SELECT p.name, COUNT(b.id) as cnt FROM publishers p "
        "JOIN books b ON b.publisher_id=p.id GROUP BY p.id ORDER BY cnt DESC"
    ).fetchall()
    authors_stats = conn.execute(
        "SELECT a.name, COUNT(b.id) as cnt FROM authors a "
        "JOIN books b ON b.author_id=a.id GROUP BY a.id ORDER BY cnt DESC LIMIT 20"
    ).fetchall()
    goals = conn.execute("SELECT * FROM reading_goals ORDER BY id DESC").fetchall()
    now_year = datetime.now(timezone.utc).year
    current_streak = reading_streak(conn)
    best_streak = max_reading_streak(conn)
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
                           publishers_stats=publishers_stats,
                           authors_stats=authors_stats,
                           goals=goals,
                           current_streak=current_streak,
                           best_streak=best_streak)


@app.route('/settings')
@login_required
def settings():
    conn = get_db()
    all_s = {}
    for row in conn.execute("SELECT key, value FROM settings"):
        all_s[row['key']] = row['value']
    defaults = {
        'dark_mode': 'false', 'show_reviews': 'true',
        'show_stats_total': 'true', 'show_stats_publishers': 'true',
        'show_stats_authors': 'true', 'show_stats_graphs': 'true',
        'show_stars': 'true', 'show_spice': 'true',
        'show_tension': 'true', 'show_fiction': 'true',
        'show_lent': 'true',
        'show_streak': 'true',
        'show_audiobook': 'true',
    }
    for k, v in defaults.items():
        all_s.setdefault(k, v)

    authors_list = conn.execute("SELECT * FROM authors ORDER BY name").fetchall()
    publishers_list = conn.execute("SELECT * FROM publishers ORDER BY name").fetchall()
    goals = conn.execute("SELECT * FROM reading_goals ORDER BY id DESC").fetchall()
    conn.close()
    return render_template('settings.html', s=all_s,
                           authors=authors_list,
                           publishers=publishers_list,
                           goals=goals,
                           now_year=datetime.now(timezone.utc).year)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ ISBN lookup
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Cover Upload
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Authors / Publishers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/authors/search')
@login_required
def search_authors():
    q = request.args.get('q', '')
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM authors WHERE name LIKE ? ORDER BY name LIMIT 10",
        (f'%{q}%',)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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


@app.route('/api/publishers/search')
@login_required
def search_publishers():
    q = request.args.get('q', '')
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM publishers WHERE name LIKE ? ORDER BY name LIMIT 10",
        (f'%{q}%',)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Books
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/books', methods=['POST'])
@login_required
def create_book():
    d = request.json
    conn = get_db()
    aid = upsert_author(conn, d.get('author', ''))
    pid = upsert_publisher(conn, d.get('publisher', ''))
    conn.execute(
        "INSERT INTO books (title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, format, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
         d.get('pages') or 0, d.get('format', 'Paperback'), d.get('release_date'),
         d.get('series'), d.get('volume'), d.get('status', 'Ungelesen'),
         1 if d.get('is_audiobook') else 0)
    )
    book_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': book_id, 'success': True})


@app.route('/api/books/<int:book_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def book_api(book_id):
    conn = get_db()
    if request.method == 'GET':
        book = conn.execute(
            "SELECT b.*, a.name as author_name, p.name as publisher_name "
            "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
            "LEFT JOIN publishers p ON b.publisher_id=p.id WHERE b.id=?", (book_id,)
        ).fetchone()
        conn.close()
        return jsonify(dict(book)) if book else (jsonify({'error': 'Nicht gefunden'}), 404)

    elif request.method == 'PUT':
        d = request.json
        aid = upsert_author(conn, d.get('author', ''))
        pid = upsert_publisher(conn, d.get('publisher', ''))
        existing = conn.execute("SELECT status, read_date FROM books WHERE id=?", (book_id,)).fetchone()
        read_date = existing['read_date'] if existing else None
        if d.get('status') == 'Gelesen' and existing and existing['status'] != 'Gelesen':
            read_date = datetime.now(timezone.utc).isoformat()
        elif d.get('status') != 'Gelesen':
            read_date = None
        conn.execute(
            "UPDATE books SET title=?, author_id=?, publisher_id=?, isbn=?, cover_url=?, "
            "genre=?, pages=?, format=?, release_date=?, series=?, volume=?, status=?, read_date=?, is_audiobook=? "
            "WHERE id=?",
            (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
             d.get('pages') or 0, d.get('format', 'Paperback'), d.get('release_date'),
             d.get('series'), d.get('volume'), d.get('status', 'Ungelesen'), read_date,
             1 if d.get('is_audiobook') else 0, book_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    elif request.method == 'DELETE':
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})


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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Wishlist
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/wishlist', methods=['POST'])
@login_required
def create_wishlist():
    d = request.json
    conn = get_db()
    aid = upsert_author(conn, d.get('author', ''))
    pid = upsert_publisher(conn, d.get('publisher', ''))
    conn.execute(
        "INSERT INTO wishlist (title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
         d.get('pages') or 0, d.get('release_date'), d.get('series'), d.get('volume'),
         d.get('status', 'Ungelesen'), 1 if d.get('is_audiobook') else 0)
    )
    wid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': wid, 'success': True})


@app.route('/api/wishlist/<int:wid>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def wishlist_api(wid):
    conn = get_db()
    if request.method == 'GET':
        item = conn.execute(
            "SELECT w.*, a.name as author_name, p.name as publisher_name "
            "FROM wishlist w LEFT JOIN authors a ON w.author_id=a.id "
            "LEFT JOIN publishers p ON w.publisher_id=p.id WHERE w.id=?", (wid,)
        ).fetchone()
        conn.close()
        return jsonify(dict(item)) if item else (jsonify({'error': 'Nicht gefunden'}), 404)

    elif request.method == 'PUT':
        d = request.json
        aid = upsert_author(conn, d.get('author', ''))
        pid = upsert_publisher(conn, d.get('publisher', ''))
        conn.execute(
            "UPDATE wishlist SET title=?, author_id=?, publisher_id=?, isbn=?, cover_url=?, "
            "genre=?, pages=?, release_date=?, series=?, volume=?, status=?, is_audiobook=? WHERE id=?",
            (d.get('title'), aid, pid, d.get('isbn'), d.get('cover_url'), d.get('genre'),
             d.get('pages') or 0, d.get('release_date'), d.get('series'), d.get('volume'),
             d.get('status', 'Ungelesen'), 1 if d.get('is_audiobook') else 0, wid)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})

    elif request.method == 'DELETE':
        conn.execute("DELETE FROM wishlist WHERE id=?", (wid,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})


@app.route('/api/wishlist/<int:wid>/buy', methods=['POST'])
@login_required
def buy_wishlist(wid):
    d = request.json
    fmt = d.get('format', 'Paperback')
    conn = get_db()
    item = conn.execute("SELECT * FROM wishlist WHERE id=?", (wid,)).fetchone()
    if not item:
        conn.close()
        return jsonify({'error': 'Nicht gefunden'}), 404
    conn.execute(
        "INSERT INTO books (title, author_id, publisher_id, isbn, cover_url, genre, "
        "pages, format, release_date, series, volume, status, is_audiobook) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item['title'], item['author_id'], item['publisher_id'], item['isbn'],
         item['cover_url'], item['genre'], item['pages'], fmt,
         item['release_date'], item['series'], item['volume'], item['status'],
         item['is_audiobook'] if 'is_audiobook' in item.keys() else 0)
    )
    book_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.execute("DELETE FROM wishlist WHERE id=?", (wid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'book_id': book_id})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Quotes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/quotes', methods=['POST'])
@login_required
def create_quote():
    d = request.json
    conn = get_db()
    conn.execute(
        "INSERT INTO quotes (book_id, quote_text, page) VALUES (?,?,?)",
        (d.get('book_id'), d.get('quote_text', ''), d.get('page'))
    )
    qid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': qid, 'success': True})


@app.route('/api/quotes/<int:qid>', methods=['DELETE'])
@login_required
def delete_quote(qid):
    conn = get_db()
    conn.execute("DELETE FROM quotes WHERE id=?", (qid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Settings
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    d = request.json
    conn = get_db()
    for key, value in d.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value))
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/settings/password', methods=['POST'])
@login_required
def change_password():
    d = request.json or {}
    new_pw = d.get('new', '').strip()
    if len(new_pw) < 4:
        return jsonify({'error': 'Passwort muss mindestens 4 Zeichen haben'}), 400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('password', ?)", (new_pw,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Reading Goals
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/reading-goals', methods=['POST'])
@login_required
def create_goal():
    d = request.json
    conn = get_db()
    conn.execute("UPDATE reading_goals SET enabled=0")
    conn.execute(
        "INSERT INTO reading_goals (goal_type, period, target, enabled) VALUES (?,?,?,1)",
        (d.get('goal_type'), d.get('period'), d.get('target'))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/reading-goals/<int:gid>/toggle', methods=['POST'])
@login_required
def toggle_goal(gid):
    conn = get_db()
    row = conn.execute("SELECT enabled FROM reading_goals WHERE id=?", (gid,)).fetchone()
    if row:
        new_val = 0 if row['enabled'] else 1
        if new_val == 1:
            conn.execute("UPDATE reading_goals SET enabled=0")
        conn.execute("UPDATE reading_goals SET enabled=? WHERE id=?", (new_val, gid))
        conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/reading-goals/<int:gid>', methods=['DELETE'])
@login_required
def delete_goal(gid):
    conn = get_db()
    conn.execute("DELETE FROM reading_goals WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Statistics charts
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/statistics/charts')
@login_required
def stats_charts():
    conn = get_db()
    period = request.args.get('period', 'monthly')
    now = datetime.now(timezone.utc)
    months_de = ['Jan', 'Feb', 'MÃ¤r', 'Apr', 'Mai', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

    labels, pages_data, books_data = [], [], []

    if period == 'weekly':
        for i in range(7, -1, -1):
            ws = now - timedelta(days=now.weekday() + 7 * i)
            ws = ws.replace(hour=0, minute=0, second=0, microsecond=0)
            we = ws + timedelta(days=7)
            labels.append(f"KW {ws.isocalendar()[1]}")
            p = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as v "
                "FROM reading_progress WHERE timestamp>=? AND timestamp<?",
                (ws.isoformat(), we.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE status='Gelesen' "
                "AND read_date>=? AND read_date<?",
                (ws.isoformat(), we.isoformat())
            ).fetchone()['v']
            books_data.append(b)

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
                "FROM reading_progress WHERE timestamp>=? AND timestamp<?",
                (start.isoformat(), end.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE status='Gelesen' "
                "AND read_date>=? AND read_date<?",
                (start.isoformat(), end.isoformat())
            ).fetchone()['v']
            books_data.append(b)

    else:  # yearly
        for i in range(4, -1, -1):
            y = now.year - i
            start = datetime(y, 1, 1)
            end = datetime(y + 1, 1, 1)
            labels.append(str(y))
            p = conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as v "
                "FROM reading_progress WHERE timestamp>=? AND timestamp<?",
                (start.isoformat(), end.isoformat())
            ).fetchone()['v']
            pages_data.append(p)
            b = conn.execute(
                "SELECT COUNT(*) as v FROM books WHERE status='Gelesen' "
                "AND read_date>=? AND read_date<?",
                (start.isoformat(), end.isoformat())
            ).fetchone()['v']
            books_data.append(b)

    conn.close()
    return jsonify({'labels': labels, 'pages': pages_data, 'books': books_data})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Serien
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/series')
@login_required
def series_list():
    conn = get_db()
    series = conn.execute(
        "SELECT s.*, COUNT(b.id) as total, "
        "SUM(CASE WHEN b.status='Gelesen' THEN 1 ELSE 0 END) as read_count "
        "FROM series s LEFT JOIN books b ON b.series_id=s.id "
        "GROUP BY s.id ORDER BY s.name"
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id ORDER BY b.title"
    ).fetchall()
    conn.close()
    return render_template('series.html', series=series, all_books=all_books)


@app.route('/series/<int:sid>')
@login_required
def series_detail(sid):
    conn = get_db()
    s = conn.execute("SELECT * FROM series WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        return redirect(url_for('series_list'))
    books = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.series_id=? ORDER BY COALESCE(b.series_order, 9999), b.id",
        (sid,)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, b.cover_url, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.series_id IS NULL OR b.series_id != ? "
        "ORDER BY b.title",
        (sid,)
    ).fetchall()
    conn.close()
    return render_template('series_detail.html', series=s, books=books, all_books=all_books)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Regale
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/shelves')
@login_required
def shelves():
    conn = get_db()
    shelves_list = conn.execute(
        "SELECT s.*, COUNT(sb.book_id) as book_count "
        "FROM shelves s LEFT JOIN shelf_books sb ON sb.shelf_id=s.id "
        "GROUP BY s.id ORDER BY s.name"
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id ORDER BY b.title"
    ).fetchall()
    conn.close()
    return render_template('shelves.html', shelves=shelves_list, all_books=all_books)


@app.route('/shelves/<int:shid>')
@login_required
def shelf_detail(shid):
    conn = get_db()
    shelf = conn.execute("SELECT * FROM shelves WHERE id=?", (shid,)).fetchone()
    if not shelf:
        conn.close()
        return redirect(url_for('shelves'))
    books = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "JOIN shelf_books sb ON sb.book_id=b.id "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE sb.shelf_id=? ORDER BY b.title",
        (shid,)
    ).fetchall()
    all_books = conn.execute(
        "SELECT b.id, b.title, b.cover_url, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "ORDER BY b.title"
    ).fetchall()
    conn.close()
    return render_template('shelf_detail.html', shelf=shelf, books=books, all_books=all_books)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  JahresrÃ¼ckblick
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/stats/year/<int:year>')
@login_required
def year_review(year):
    conn = get_db()
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    books_read = conn.execute(
        "SELECT b.*, a.name as author_name FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "WHERE b.status='Gelesen' AND b.read_date >= ? AND b.read_date < ? "
        "ORDER BY b.read_date",
        (start.isoformat(), end.isoformat())
    ).fetchall()
    total_pages = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) as t "
        "FROM reading_progress WHERE timestamp >= ? AND timestamp < ?",
        (start.isoformat(), end.isoformat())
    ).fetchone()['t']
    genres = {}
    for b in books_read:
        if b['genre']:
            for g in b['genre'].split(','):
                g = g.strip()
                if g:
                    genres[g] = genres.get(g, 0) + 1
    top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:5]
    months_de = ['Jan', 'Feb', 'MÃ¤r', 'Apr', 'Mai', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
    monthly = []
    for m in range(1, 13):
        ms = datetime(year, m, 1)
        me = datetime(year, m + 1, 1) if m < 12 else end
        c = conn.execute(
            "SELECT COUNT(*) as c FROM books WHERE status='Gelesen' "
            "AND read_date >= ? AND read_date < ?",
            (ms.isoformat(), me.isoformat())
        ).fetchone()['c']
        monthly.append({'label': months_de[m - 1], 'count': c})
    best = conn.execute(
        "SELECT b.*, a.name as author_name, r.stars FROM books b "
        "LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN ratings r ON r.book_id=b.id "
        "WHERE b.status='Gelesen' AND b.read_date >= ? AND b.read_date < ? "
        "AND r.stars IS NOT NULL ORDER BY r.stars DESC LIMIT 1",
        (start.isoformat(), end.isoformat())
    ).fetchone()
    years_rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', read_date) as y FROM books "
        "WHERE status='Gelesen' AND read_date IS NOT NULL ORDER BY y DESC"
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Export
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/export/csv')
@login_required
def export_csv():
    conn = get_db()
    books = conn.execute(
        "SELECT b.title, a.name as author, p.name as publisher, b.isbn, "
        "b.genre, b.pages, b.format, b.release_date, b.series, b.volume, "
        "b.status, b.read_date, b.added_date, b.lent_to, b.lent_date "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id ORDER BY b.added_date DESC"
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
    conn = get_db()
    books = conn.execute(
        "SELECT b.*, a.name as author_name, p.name as publisher_name "
        "FROM books b LEFT JOIN authors a ON b.author_id=a.id "
        "LEFT JOIN publishers p ON b.publisher_id=p.id ORDER BY b.added_date DESC"
    ).fetchall()
    conn.close()
    data = [dict(b) for b in books]
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=reading_diary.json'}
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Buchnotizen
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/books/<int:book_id>/notes', methods=['GET', 'POST'])
@login_required
def book_notes(book_id):
    conn = get_db()
    if request.method == 'GET':
        notes = conn.execute(
            "SELECT * FROM book_notes WHERE book_id=? ORDER BY created_at ASC",
            (book_id,)
        ).fetchall()
        conn.close()
        return jsonify([dict(n) for n in notes])
    d = request.json
    conn.execute(
        "INSERT INTO book_notes (book_id, chapter, content) VALUES (?,?,?)",
        (book_id, (d.get('chapter') or '').strip(), d.get('content', ''))
    )
    nid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': nid, 'success': True})


@app.route('/api/notes/<int:nid>', methods=['PUT', 'DELETE'])
@login_required
def note_api(nid):
    conn = get_db()
    if request.method == 'PUT':
        d = request.json
        conn.execute(
            "UPDATE book_notes SET chapter=?, content=? WHERE id=?",
            ((d.get('chapter') or '').strip(), d.get('content', ''), nid)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    conn.execute("DELETE FROM book_notes WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Regale
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/shelves', methods=['POST'])
@login_required
def create_shelf():
    d = request.json
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name erforderlich'}), 400
    conn = get_db()
    conn.execute("INSERT INTO shelves (name) VALUES (?)", (name,))
    shid = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
    conn.commit()
    conn.close()
    return jsonify({'id': shid, 'success': True})


@app.route('/api/shelves/<int:shid>', methods=['PUT', 'DELETE'])
@login_required
def shelf_api(shid):
    conn = get_db()
    if request.method == 'PUT':
        d = request.json
        conn.execute("UPDATE shelves SET name=? WHERE id=?", ((d.get('name') or '').strip(), shid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    conn.execute("DELETE FROM shelves WHERE id=?", (shid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/shelves/<int:shid>/books', methods=['POST'])
@login_required
def add_to_shelf(shid):
    d = request.json
    book_id = d.get('book_id')
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO shelf_books (shelf_id, book_id) VALUES (?,?)", (shid, book_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/shelves/<int:shid>/books/<int:bid>', methods=['DELETE'])
@login_required
def remove_from_shelf(shid, bid):
    conn = get_db()
    conn.execute("DELETE FROM shelf_books WHERE shelf_id=? AND book_id=?", (shid, bid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Serien
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route('/api/series', methods=['GET', 'POST'])
@login_required
def series_api():
    conn = get_db()
    if request.method == 'GET':
        rows = conn.execute("SELECT * FROM series ORDER BY name").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    d = request.json
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name erforderlich'}), 400
    conn.execute("INSERT OR IGNORE INTO series (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM series WHERE name=?", (name,)).fetchone()
    conn.commit()
    conn.close()
    return jsonify({'id': row['id'], 'success': True})


@app.route('/api/series/<int:sid>', methods=['DELETE'])
@login_required
def delete_series(sid):
    conn = get_db()
    conn.execute("UPDATE books SET series_id=NULL, series_order=NULL WHERE series_id=?", (sid,))
    conn.execute("DELETE FROM series WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/books/<int:book_id>/series', methods=['PUT'])
@login_required
def assign_series(book_id):
    d = request.json
    conn = get_db()
    conn.execute(
        "UPDATE books SET series_id=?, series_order=? WHERE id=?",
        (d.get('series_id') or None, d.get('series_order') or None, book_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  API â€“ Verliehen
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  PWA Icons (generated at runtime)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


@app.route('/icon-<int:size>.png')
def serve_icon(size):
    if size not in (192, 512):
        size = 192
    return Response(make_png(size), mimetype='image/png')


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  DB Init
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS publishers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
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
    """)
    # Migrations: neue Spalten zu bestehenden Tabellen hinzufÃ¼gen
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
    defaults = [
        ('dark_mode', 'false'), ('show_reviews', 'true'),
        ('show_stats_total', 'true'), ('show_stats_publishers', 'true'),
        ('show_stats_authors', 'true'), ('show_stats_graphs', 'true'),
        ('show_stars', 'true'), ('show_spice', 'true'),
        ('show_tension', 'true'), ('show_fiction', 'true'),
        ('show_audiobook', 'true'),
    ]
    for k, v in defaults:
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=7443, debug=False)
