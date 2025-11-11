// Globale Variablen
let currentToken = '';
let currentServerUrl = '';
let currentPage = 'dashboard';
let editModeCoverData = null; // Speichert Cover-Daten für Edit-Modus

// WebSocket Variablen
let ws = null;
let wsReconnectTimer = null;
let wsReconnectAttempts = 0;
const WS_MAX_RECONNECT_ATTEMPTS = 10;
const WS_RECONNECT_DELAY = 3000;

// ===== THEME MANAGEMENT =====
// Theme-System: Dark Mode Support
function initTheme() {
    // Versuche gespeichertes Theme zu laden
    const savedTheme = localStorage.getItem('readingDiaryTheme');
    
    // Wenn kein gespeichertes Theme vorhanden, verwende System-Präferenz
    if (savedTheme) {
        setTheme(savedTheme);
    } else {
        // Prüfe System-Theme-Präferenz
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        setTheme(prefersDark ? 'dark' : 'light');
    }
    
    // Event-Listener für Theme-Toggle hinzufügen
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('change', (e) => {
            const newTheme = e.target.checked ? 'dark' : 'light';
            setTheme(newTheme);
            localStorage.setItem('readingDiaryTheme', newTheme);
        });
    }
    
    // System-Theme-Änderungen überwachen
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
        // Nur automatisch wechseln wenn Nutzer keine manuelle Präferenz gesetzt hat
        if (!localStorage.getItem('readingDiaryTheme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });
}

function setTheme(theme) {
    const html = document.documentElement;
    const themeToggle = document.getElementById('themeToggle');
    
    if (theme === 'dark') {
        html.setAttribute('data-theme', 'dark');
        if (themeToggle) themeToggle.checked = true;
    } else {
        html.removeAttribute('data-theme');
        if (themeToggle) themeToggle.checked = false;
    }
}

function getTheme() {
    return document.documentElement.getAttribute('data-theme') || 'light';
}

// Theme beim Seitenload initialisieren (vor allen anderen Scripts)
initTheme();

// Service Worker Registration für PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/static/sw.js')
            .then(function(registration) {
                console.log('ServiceWorker registration successful with scope: ', registration.scope);
            }, function(err) {
                console.warn('ServiceWorker registration failed:', err);
            });
    });
}

// PWA Install Prompt
let deferredPrompt;
let installButton;

window.addEventListener('beforeinstallprompt', (e) => {
    // Prevent Chrome 67 and earlier from automatically showing the prompt
    e.preventDefault();
    // Stash the event so it can be triggered later
    deferredPrompt = e;
    // Show install button
    showInstallPromotion();
});

function showInstallPromotion() {
    // Prüfe ob bereits installiert
    if (window.matchMedia('(display-mode: standalone)').matches) {
        console.log('App is already installed');
        return;
    }

    // Floating Button erstellen (für bessere Sichtbarkeit)
    if (!installButton) {
        installButton = document.createElement('button');
        installButton.className = 'btn btn-primary install-btn';
        installButton.innerHTML = '<i class="fas fa-download"></i> App installieren';
        
        // Mobile-optimiertes Styling
        const isMobile = window.innerWidth <= 768;
        installButton.style.cssText = `
            position: fixed;
            bottom: ${isMobile ? '80px' : '20px'};
            right: ${isMobile ? '16px' : '20px'};
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            border-radius: 50px;
            padding: ${isMobile ? '10px 16px' : '12px 20px'};
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            color: white;
            font-weight: 600;
            white-space: nowrap;
            animation: pulseInstall 2s infinite;
        `;
        
        installButton.addEventListener('click', installApp);
        document.body.appendChild(installButton);
    }
    
    // Verstecke Button nach 15 Sekunden auf Mobile, 10 auf Desktop
    const isMobile = window.innerWidth <= 768;
    setTimeout(() => {
        if (installButton && installButton.parentNode) {
            installButton.remove();
            installButton = null;
        }
    }, isMobile ? 15000 : 10000);
}

async function installApp() {
    if (deferredPrompt) {
        // Show the prompt
        deferredPrompt.prompt();
        // Wait for the user to respond to the prompt
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`User response to the install prompt: ${outcome}`);
        
        if (outcome === 'accepted') {
            hideInstallButton();
            showMessage(null, 'Reading Diary wird installiert...', 'success');
        }
        
        // Clear the deferredPrompt variable
        deferredPrompt = null;
    } else {
        // Fallback für Browser ohne beforeinstallprompt
        showInstallInstructions();
    }
}

function hideInstallButton() {
    if (installButton && installButton.parentNode) {
        installButton.remove();
        installButton = null;
    }
}

function showInstallInstructions() {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isAndroid = /Android/.test(navigator.userAgent);
    
    let instructions = '';
    
    if (isIOS) {
        instructions = 'Tippen Sie auf das Teilen-Symbol und dann auf "Zum Home-Bildschirm"';
    } else if (isAndroid) {
        instructions = 'Tippen Sie auf das Menü und dann auf "Zum Startbildschirm hinzufügen"';
    } else {
        instructions = 'Verwenden Sie das Browser-Menü, um diese App zu installieren';
    }
    
    // Zeige einfache Installationsanweisungen für manuelle Installation
    const instructionsDiv = document.createElement('div');
    instructionsDiv.id = 'manual-install-instructions';
    instructionsDiv.innerHTML = `
        <div style="background: #e3f2fd; border: 1px solid #2196f3; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <h4>📱 PWA Installation</h4>
            <p><strong>Anleitung:</strong> ${instructions}</p>
            <p><strong>Detaillierte Anleitung:</strong> <a href="/pwa-help" target="_blank" style="color: #2196f3; text-decoration: underline;">PWA-Hilfe →</a></p>
        </div>
    `;
    
    const dashboard = document.querySelector('.dashboard-section');
    if (dashboard) {
        dashboard.insertBefore(instructionsDiv, dashboard.firstChild);
        
        // Nachricht nach 25 Sekunden ausblenden
        setTimeout(() => {
            const instrMsg = document.getElementById('manual-install-instructions');
            if (instrMsg) {
                instrMsg.style.opacity = '0';
                instrMsg.style.transition = 'opacity 0.5s';
                setTimeout(() => instrMsg.remove(), 500);
            }
        }, 25000);
    }
}

// Detect if app is installed
window.addEventListener('appinstalled', (evt) => {
    console.log('Reading Diary PWA was installed');
    showMessage(null, 'Reading Diary wurde erfolgreich installiert!', 'success');
});

// Hilfsfunktionen
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateString) {
    if (!dateString) return 'Unbekannt';
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString('de-DE');
    } catch (e) {
        return 'Unbekannt';
    }
}

// Utility-Funktionen für UI
function generateStarsDisplay(rating) {
    const stars = [];
    for (let i = 1; i <= 5; i++) {
        stars.push(i <= rating ? '★' : '☆');
    }
    return stars.join('');
}

function generateSpiceDisplay(spice) {
    const chilis = [];
    for (let i = 1; i <= 5; i++) {
        chilis.push(i <= spice ? '🌶️' : '❌');
    }
    return chilis.join('');
}

function convertMarkdownToHtml(markdown) {
    if (!markdown) return '';
    
    // Vollständige Markdown-Konvertierung
    let html = escapeHtml(markdown);
    
    // Code blocks ```code```
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    
    // Inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Headers (von größer zu kleiner für richtige Reihenfolge)
    html = html.replace(/^#### (.*$)/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');
    
    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Italic *text*
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
    
    // Strikethrough ~~text~~
    html = html.replace(/~~(.*?)~~/g, '<s>$1</s>');
    
    // Links [text](url)
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    
    // Unordered lists
    html = html.replace(/^[\s]*[-*+][\s]+(.*$)/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    
    // Ordered lists
    html = html.replace(/^[\s]*\d+\.[\s]+(.*$)/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, function(match) {
        // Nur ersetzen wenn es nicht schon in <ul> ist
        if (!match.includes('<ul>')) {
            return '<ol>' + match + '</ol>';
        }
        return match;
    });
    
    // Blockquotes
    html = html.replace(/^[\s]*>(.*$)/gm, '<blockquote>$1</blockquote>');
    
    // Horizontal rules
    html = html.replace(/^[\s]*---[\s]*$/gm, '<hr>');
    
    // Paragraphs (split by double line breaks)
    const paragraphs = html.split(/\n\s*\n/);
    html = paragraphs.map(p => {
        p = p.trim();
        if (p && !p.startsWith('<h') && !p.startsWith('<ul>') && !p.startsWith('<ol>') && 
            !p.startsWith('<blockquote>') && !p.startsWith('<hr>') && !p.startsWith('<pre>')) {
            return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
        }
        return p.replace(/\n/g, '<br>');
    }).join('\n');
    
    // Single line breaks
    html = html.replace(/\n/g, '<br>');
    
    return html;
}

function updateProgressDisplay(currentPage, totalPages, progressBar, progressText) {
    const percentage = totalPages > 0 ? Math.round((currentPage / totalPages) * 100) : 0;
    if (progressBar) {
        progressBar.style.width = `${percentage}%`;
    }
    if (progressText) {
        progressText.textContent = `${percentage}% gelesen`;
    }
}

// Message-System
function showMessage(element, message, type = 'info') {
    // Wenn kein Element angegeben, versuche eine globale Nachricht zu zeigen
    if (!element) {
        console.log('[showMessage] Zeige Nachricht:', message, 'Typ:', type);
        
        // Erstelle temporäre Nachricht im Header oder Modal
        const tempMessage = document.createElement('div');
        tempMessage.className = `message ${type}`;
        tempMessage.textContent = message;
        tempMessage.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-weight: 500;
            z-index: 10000;
            max-width: 400px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            animation: slideIn 0.3s ease-out;
        `;
        
        // Farben basierend auf Typ
        switch (type) {
            case 'success':
                tempMessage.style.backgroundColor = '#22c55e';
                break;
            case 'error':
                tempMessage.style.backgroundColor = '#ef4444';
                break;
            case 'warning':
                tempMessage.style.backgroundColor = '#f59e0b';
                break;
            default:
                tempMessage.style.backgroundColor = '#3b82f6';
        }
        
        document.body.appendChild(tempMessage);
        console.log('[showMessage] Nachricht zu Body hinzugefügt');
        
        // Nach 5 Sekunden automatisch entfernen (verlängert von 3)
        setTimeout(() => {
            if (document.body.contains(tempMessage)) {
                tempMessage.style.opacity = '0';
                tempMessage.style.transition = 'opacity 0.3s ease-out';
                setTimeout(() => {
                    if (document.body.contains(tempMessage)) {
                        document.body.removeChild(tempMessage);
                    }
                }, 300);
            }
        }, 5000);
        
        return;
    }
    
    // Bestehende Implementierung für Element-basierte Nachrichten
    element.textContent = message;
    element.className = `message ${type}`;
    element.style.display = 'block';
    
    // Nach 5 Sekunden verstecken
    setTimeout(() => {
        element.style.display = 'none';
    }, 5000);
}

// Beim Laden der Seite
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // Verwende relative URLs für API-Aufrufe
    // Das funktioniert sowohl mit direktem Zugriff als auch mit Nginx Reverse Proxy
    // Nginx sollte die API-Aufrufe an das Backend weiterleiten
    currentServerUrl = '';  // Leer = relative URLs
    
    // Setze WebSocket-URL basierend auf aktuellem Location
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    currentServerUrl = `${window.location.protocol}//${wsHost}`;
    
    console.log('Verwende relative URLs für API-Aufrufe');
    console.log('Window location:', window.location.href);
    console.log('Server URL für WebSocket:', currentServerUrl);
    
    // Gespeicherte Anmeldedaten laden
    const savedToken = localStorage.getItem('token');
    
    if (savedToken) {
        currentToken = savedToken;
        showMainApp();
    }
    
    setupEventListeners();
}

function setupEventListeners() {
    // Login-Events
    document.getElementById('login').addEventListener('click', login);
    document.getElementById('logout').addEventListener('click', logout);
    
    // Navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const page = e.currentTarget.dataset.page;
            navigateToPage(page);
        });
    });
    
    // Modal
    document.getElementById('closeModal').addEventListener('click', closeModal);
    document.getElementById('modal').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            closeModal();
        }
    });
    
    // Suchfelder
    document.getElementById('booksSearch').addEventListener('input', debounce(searchBooks, 300));
    document.getElementById('wishlistSearch').addEventListener('input', debounce(searchWishlist, 300));
    document.getElementById('quotesSearch').addEventListener('input', debounce(searchQuotes, 300));
    
    // Buttons
    document.getElementById('addBook').addEventListener('click', () => showBookModal({}));
    document.getElementById('addWishlistItem').addEventListener('click', () => showAddWishlistModal());
    document.getElementById('addQuote').addEventListener('click', () => showAddQuoteModal());
}

// API-Funktionen
async function apiCall(endpoint, options = {}) {
    const url = `${currentServerUrl}/api${endpoint}`;
    const config = {
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${currentToken}`
        },
        ...options
    };
    
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    
    try {
        const response = await fetch(url, config);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Ein Fehler ist aufgetreten');
        }
        
        return data;
    } catch (error) {
        console.error('API-Fehler:', error);
        throw error;
    }
}

// Login-Funktionen

async function login() {
    const password = document.getElementById('password').value;
    const messageEl = document.getElementById('loginMessage');
    
    if (!password) {
        showMessage(messageEl, 'Bitte geben Sie ein Passwort ein.', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            currentToken = data.token;
            
            // Token speichern
            localStorage.setItem('token', data.token);
            
            showMainApp();
        } else {
            throw new Error(data.error || 'Anmeldung fehlgeschlagen');
        }
    } catch (error) {
        showMessage(messageEl, error.message, 'error');
    }
}

function logout() {
    // WebSocket trennen
    disconnectWebSocket();
    
    localStorage.removeItem('token');
    currentToken = '';
    
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('mainApp').style.display = 'none';
    document.getElementById('password').value = '';
}

function showMainApp() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('mainApp').style.display = 'flex';
    
    // WebSocket verbinden
    connectWebSocket();
    
    // Dashboard laden
    loadDashboard();
    loadReadingGoalProgress();
}

// Navigation
function navigateToPage(page) {
    // Aktive Klassen entfernen
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.page').forEach(pageEl => pageEl.classList.remove('active'));
    
    // Neue Seite aktivieren
    document.querySelector(`[data-page="${page}"]`).classList.add('active');
    document.getElementById(page).classList.add('active');
    
    currentPage = page;
    
    // Seitenspezifische Daten laden
    switch (page) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'books':
            loadBooks();
            break;
        case 'wishlist':
            loadWishlist();
            break;
        case 'quotes':
            loadQuotes();
            break;
        case 'statistics':
            loadStatistics();
            break;
        case 'settings':
            loadSettings();
            break;
    }
}

// Dashboard
async function loadDashboard() {
    try {
        const stats = await apiCall('/stats');
        
        // Statistik-Karten aktualisieren
        document.getElementById('totalBooks').textContent = stats.totalBooks;
        document.getElementById('readBooks').textContent = stats.readBooks;
        document.getElementById('totalQuotes').textContent = stats.totalQuotes;
        
        // Aktuell gelesene Bücher anzeigen
        const currentlyReadingEl = document.getElementById('currentlyReadingList');
        if (currentlyReadingEl) {
            currentlyReadingEl.innerHTML = '';
            
            if (stats.currentlyReading && stats.currentlyReading.length > 0) {
                stats.currentlyReading.forEach(book => {
                    const bookCard = createBookCard(book);
                    currentlyReadingEl.appendChild(bookCard);
                });
            } else {
                currentlyReadingEl.innerHTML = '<p>Gerade liest du keine Bücher.</p>';
            }
        }
        
        // Neueste Bücher anzeigen
        const recentBooksEl = document.getElementById('recentBooksList');
        recentBooksEl.innerHTML = '';
        
        if (stats.recentBooks && stats.recentBooks.length > 0) {
            stats.recentBooks.forEach(book => {
                const bookCard = createBookCard(book);
                recentBooksEl.appendChild(bookCard);
            });
        } else {
            recentBooksEl.innerHTML = '<p>Noch keine Bücher hinzugefügt.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden des Dashboards:', error);
    }
}

async function loadReadingGoalProgress() {
    try {
        const goal = await apiCall('/reading-goal');
        const progressEl = document.getElementById('readingGoalProgress');
        
        if (goal.enabled) {
            const percentage = Math.min((goal.current / goal.target) * 100, 100);
            progressEl.innerHTML = `Leseziel: ${goal.current}/${goal.target} (${percentage.toFixed(0)}%)`;
            progressEl.style.display = 'block';
        } else {
            progressEl.style.display = 'none';
        }
    } catch (error) {
        console.error('Fehler beim Laden des Leseziels:', error);
    }
}

// Bücher
async function loadBooks(search = '', preserveScroll = false) {
    try {
        const books = await apiCall(`/books${search ? `?search=${encodeURIComponent(search)}` : ''}`);
        const booksListEl = document.getElementById('booksList');
        
        // Scroll-Position speichern
        const scrollParent = booksListEl.parentElement;
        const scrollPos = preserveScroll ? scrollParent.scrollTop : 0;
        
        booksListEl.innerHTML = '';
        
        if (books.length > 0) {
            books.forEach(book => {
                const bookItem = createBookListItem(book);
                booksListEl.appendChild(bookItem);
            });
        } else {
            booksListEl.innerHTML = '<div class="book-item"><p>Keine Bücher gefunden.</p></div>';
        }
        
        // Scroll-Position wiederherstellen
        if (preserveScroll) {
            scrollParent.scrollTop = scrollPos;
        }
    } catch (error) {
        console.error('Fehler beim Laden der Bücher:', error);
    }
}

function searchBooks() {
    const search = document.getElementById('booksSearch').value;
    loadBooks(search);
}

function createBookCard(book) {
    const card = document.createElement('div');
    card.className = 'book-card';
    card.onclick = () => showBookDetails(book.id);
    
    const coverImageUrl = book.cover_image 
        ? `/uploads/covers/${book.cover_image}` 
        : (book.coverImage ? `/uploads/covers/${book.coverImage}` : null);
    
    card.innerHTML = `
        <div class="book-card-cover">
            ${coverImageUrl ? `<img src="${coverImageUrl}" alt="Cover">` : '<i class="fas fa-book"></i>'}
        </div>
        <div class="book-card-content">
            <div class="book-card-title">${escapeHtml(book.title)}</div>
            <div class="book-card-author">${escapeHtml(book.author)}</div>
        </div>
    `;
    
    return card;
}

function createBookListItem(book) {
    const item = document.createElement('div');
    item.className = 'book-item';
    item.onclick = () => showBookDetails(book.id);
    
    // Status basierend auf neuem System oder Fallback auf altes System
    let currentStatus = book.status || (book.isRead || book.is_read ? 'Gelesen' : 'Ungelesen');
    
    // Status-Badge mit Dropdown für Änderung
    let statusBadgeClass = 'unread';
    if (currentStatus === 'Gelesen') statusBadgeClass = 'read';
    else if (currentStatus === 'Am Lesen') statusBadgeClass = 'reading';
    
    const statusDropdown = `
        <div class="status-dropdown">
            <span class="status-badge ${statusBadgeClass}">${currentStatus}</span>
            <select class="status-select" onchange="changeBookStatus(${book.id}, this.value)" onclick="event.stopPropagation()">
                <option value="Ungelesen" ${currentStatus === 'Ungelesen' ? 'selected' : ''}>Ungelesen</option>
                <option value="Am Lesen" ${currentStatus === 'Am Lesen' ? 'selected' : ''}>Am Lesen</option>
                <option value="Gelesen" ${currentStatus === 'Gelesen' ? 'selected' : ''}>Gelesen</option>
            </select>
        </div>
    `;
    
    const coverImageUrl = book.cover_image 
        ? `/uploads/covers/${book.cover_image}` 
        : (book.coverImage ? `/uploads/covers/${book.coverImage}` : null);
    
    item.innerHTML = `
        <div class="book-cover">
            ${coverImageUrl ? `<img src="${coverImageUrl}" alt="Cover">` : '<i class="fas fa-book"></i>'}
        </div>
        <div class="book-info">
            <div class="book-title">${escapeHtml(book.title)}</div>
            <div class="book-meta">von ${escapeHtml(book.author)}</div>
            <div class="book-meta">${escapeHtml(book.publisher)} • ${formatDate(book.publish_date || book.publishDate)}</div>
        </div>
        <div class="book-actions">
            ${statusDropdown}
        </div>
    `;
    
    return item;
}

async function showBookDetails(bookId) {
    try {
        const book = await apiCall(`/books/${bookId}`);
        showBookModal(book);
    } catch (error) {
        alert('Fehler beim Laden der Buchdetails: ' + error.message);
    }
}

function showBookModal(book) {
    const isEdit = !!book.id;
    const title = isEdit ? 'Buchdetails' : 'Neues Buch hinzufügen';
    
    // Debug: Prüfe ob ISBN vorhanden ist
    if (isEdit) {
        console.log('=== ISBN DEBUG START ===');
        console.log('[showBookModal] Komplettes Buch-Objekt:', book);
        console.log('[showBookModal] book.isbn Wert:', book.isbn);
        console.log('[showBookModal] book.isbn Typ:', typeof book.isbn);
        console.log('[showBookModal] book.isbn === undefined?', book.isbn === undefined);
        console.log('[showBookModal] book.isbn === null?', book.isbn === null);
        console.log('[showBookModal] book.isbn === ""?', book.isbn === '');
        console.log('[showBookModal] Template wird ISBN setzen auf:', book.isbn || '');
        console.log('=== ISBN DEBUG END ===');
    }
    
    let modalBody = '';
    
    if (isEdit) {
        // Detailansicht für existierende Bücher
        const progressPercent = book.pages ? Math.round(((book.readingProgress || book.reading_progress || 0) / book.pages) * 100) : 0;
        
        modalBody = `
            <div id="bookDetailView" data-book-id="${book.id}">
                <!-- Grundinformationen (nur anzeigen) -->
                <div id="basicInfoDisplay" class="book-section">
                    <div class="section-header">
                        <h3>Grundinformationen</h3>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleEditMode('basicInfo')">Bearbeiten</button>
                    </div>
                    <div class="book-info-grid">
                        <div><strong>Titel:</strong> ${escapeHtml(book.title || '')}</div>
                        <div><strong>Autor:</strong> ${escapeHtml(book.author || '')}</div>
                        ${book.isbn ? `<div><strong>ISBN:</strong> ${escapeHtml(book.isbn)}</div>` : ''}
                        <div><strong>Genre:</strong> ${escapeHtml(book.genre || '')}</div>
                        <div><strong>Seiten:</strong> ${book.pages || 0}</div>
                        <div><strong>Format:</strong> ${escapeHtml(book.format || '')}</div>
                        <div><strong>Verlag:</strong> ${escapeHtml(book.publisher || '')}</div>
                        <div><strong>Erscheinungsdatum:</strong> ${formatDate(book.publish_date || book.publishDate)}</div>
                        <div><strong>Reihe:</strong> ${escapeHtml(book.series || 'Keine')}</div>
                        <div><strong>Band:</strong> ${book.volume || 'Kein Band'}</div>
                        <div><strong>Status:</strong> ${book.status || (book.isRead || book.is_read ? 'Gelesen' : 'Ungelesen')}</div>
                    </div>
                </div>

                <!-- Bearbeitungsformular für Grundinformationen (versteckt) -->
                <div id="basicInfoEdit" class="book-section" style="display: none;">
                    <div class="section-header">
                        <h3>Grundinformationen bearbeiten</h3>
                        <div>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelEditMode('basicInfo')">Abbrechen</button>
                            <button type="button" class="btn btn-sm btn-primary" onclick="saveBasicInfo(${book.id})">Speichern</button>
                        </div>
                    </div>
                    <!-- Cover im Bearbeitungsmodus -->
                    <div class="form-group full-width">
                        <label>Cover</label>
                        <div class="cover-display" id="editCoverDisplay">
                            ${(book.cover_image || book.coverImage) ? 
                                `<img src="/uploads/covers/${book.cover_image || book.coverImage}" alt="Book Cover" class="book-cover-large">` : 
                                '<div class="no-cover"><i class="fas fa-book"></i><p>Kein Cover vorhanden</p></div>'
                            }
                        </div>
                        <small>Cover wird automatisch aktualisiert wenn ISBN-Daten abgerufen werden oder manuell hochgeladen</small>
                    </div>
                    
                    <!-- Cover Upload für Edit-Modus -->
                    <div class="form-group full-width">
                        <label for="editBookCover">Cover manuell hochladen (optional)</label>
                        <input type="file" id="editBookCover" accept="image/*" onchange="previewEditBookCover(this)">
                        <small>Unterstützte Formate: JPG, PNG, WebP</small>
                        <div id="editCoverErrorMessage" style="margin-top: 8px;"></div>
                    </div>
                    
                    <div class="form-grid">
                        <div class="form-group full-width">
                            <label for="bookISBN">ISBN (optional)</label>
                            <div class="isbn-buttons-group">
                                <button type="button" class="btn btn-primary btn-sm" onclick="searchByISBNEdit(event, ${book.id})">
                                    <i class="fas fa-search"></i> Daten abrufen
                                </button>
                                <button type="button" class="btn btn-secondary btn-sm" onclick="startBarcodeScannerEdit(${book.id})">
                                    <i class="fas fa-barcode"></i> Scannen
                                </button>
                            </div>
                            <input type="text" id="bookISBN" value="${book.isbn || ''}" placeholder="ISBN eingeben...">
                            <small>ISBN eingeben und "Daten abrufen" klicken um Felder und Cover zu aktualisieren</small>
                        </div>
                        <div class="form-group full-width">
                            <label for="bookTitle">Titel *</label>
                            <input type="text" id="bookTitle" value="${book.title || ''}" required>
                        </div>
                        <div class="form-group">
                            <label for="bookAuthor">Autor *</label>
                            <input type="text" id="bookAuthor" value="${book.author || ''}" required>
                        </div>
                        <div class="form-group">
                            <label for="bookGenre">Genre *</label>
                            <div class="autocomplete-container">
                                <input type="text" id="bookGenre" placeholder="Genre eingeben..." required>
                                <div id="genreSuggestions" class="autocomplete-suggestions"></div>
                            </div>
                        </div>
                        <div class="form-group">
                            <label for="bookPages">Seiten *</label>
                            <input type="number" id="bookPages" value="${book.pages || ''}" required min="1">
                        </div>
                        <div class="form-group">
                            <label for="bookFormat">Format *</label>
                            <select id="bookFormat" required>
                                <option value="">Format wählen</option>
                                <option value="Hardcover" ${book.format === 'Hardcover' ? 'selected' : ''}>Hardcover</option>
                                <option value="Paperback" ${book.format === 'Paperback' ? 'selected' : ''}>Paperback</option>
                                <option value="eBook" ${book.format === 'eBook' ? 'selected' : ''}>eBook</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="bookPublisher">Verlag *</label>
                            <div class="autocomplete-container">
                                <input type="text" id="bookPublisher" placeholder="Verlag eingeben..." required>
                                <div id="publisherSuggestions" class="autocomplete-suggestions"></div>
                            </div>
                        </div>
                        <div class="form-group">
                            <label for="bookPublishDate">Erscheinungsdatum *</label>
                            <input type="date" id="bookPublishDate" value="${book.publish_date ? book.publish_date.split('T')[0] : (book.publishDate ? book.publishDate.split('T')[0] : '')}" required>
                        </div>
                        <div class="form-group">
                            <label for="bookSeries">Reihe</label>
                            <input type="text" id="bookSeries" value="${book.series || ''}">
                        </div>
                        <div class="form-group">
                            <label for="bookVolume">Band</label>
                            <input type="text" id="bookVolume" value="${book.volume || ''}">
                        </div>
                        <div class="form-group">
                            <label for="bookStatus">Status</label>
                            <select id="bookStatus">
                                <option value="Ungelesen" ${(book.status === 'Ungelesen' || (!book.status && !(book.isRead || book.is_read))) ? 'selected' : ''}>Ungelesen</option>
                                <option value="Am Lesen" ${book.status === 'Am Lesen' ? 'selected' : ''}>Am Lesen</option>
                                <option value="Gelesen" ${(book.status === 'Gelesen' || (!book.status && (book.isRead || book.is_read))) ? 'selected' : ''}>Gelesen</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Lesefortschritt (immer editierbar) -->
                <div class="book-section">
                    <div class="section-header">
                        <h3>Lesefortschritt</h3>
                    </div>
                    <div class="progress-section">
                        <div class="form-group">
                            <label for="currentPage">Aktuelle Seite</label>
                            <input type="number" id="currentPage" value="${book.readingProgress || book.reading_progress || 0}" min="0" max="${book.pages || 999}">
                            <small>von ${book.pages || 0} Seiten</small>
                        </div>
                        <div class="progress-display">
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${progressPercent}%"></div>
                            </div>
                            <span class="progress-text">${progressPercent}% gelesen</span>
                        </div>
                        <button type="button" class="btn btn-primary" onclick="saveProgress(${book.id})">Fortschritt speichern</button>
                        
                        <!-- Fortschritt-Historie -->
                        <div id="progressHistory" class="progress-history">
                            <p><em>Lade Fortschritt-Historie...</em></p>
                        </div>
                    </div>
                </div>

                <!-- Bewertungen (anzeigen/bearbeiten) -->
                <div id="ratingsDisplay" class="book-section">
                    <div class="section-header">
                        <h3>Bewertungen</h3>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleEditMode('ratings')">Bearbeiten</button>
                    </div>
                    <div class="ratings-display">
                        <div><strong>Bewertung:</strong> ${generateStarsDisplay(book.rating || 0)} (${book.rating || 0}/5)</div>
                        <div><strong>Spice Level:</strong> ${generateSpiceDisplay(book.spice || 0)} (${book.spice || 0}/5)</div>
                        <div><strong>Spannung:</strong> ${book.tension || 0}/10</div>
                        <div><strong>Typ:</strong> ${book.fiction === true || book.fiction === 'Fiction' ? 'Fiction' : 'Non-Fiction'}</div>
                    </div>
                </div>

                <!-- Bewertungen bearbeiten (versteckt) -->
                <div id="ratingsEdit" class="book-section" style="display: none;">
                    <div class="section-header">
                        <h3>Bewertungen bearbeiten</h3>
                        <div>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelEditMode('ratings')">Abbrechen</button>
                            <button type="button" class="btn btn-sm btn-primary" id="saveRatingsBtn" onclick="saveRatings(${book.id})" style="display: none;">Speichern</button>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Bewertung (Sterne)</label>
                            <div class="rating" data-rating="rating" data-value="${book.rating || 0}">
                                ${[1,2,3,4,5].map(i => `<span class="star ${i <= (book.rating || 0) ? 'active' : ''}" data-value="${i}">★</span>`).join('')}
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Spice Level</label>
                            <div class="rating" data-rating="spice" data-value="${book.spice || 0}">
                                ${[1,2,3,4,5].map(i => `<span class="star ${i <= (book.spice || 0) ? 'active' : ''}" data-value="${i}">${i <= (book.spice || 0) ? '🌶️' : '❌'}</span>`).join('')}
                            </div>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="bookTension">Spannung (1-10)</label>
                            <input type="range" id="bookTension" value="${book.tension || 0}" min="0" max="10">
                            <span id="tensionValue">${book.tension || 0}</span>
                        </div>
                        <div class="form-group">
                            <label for="bookFiction">Typ</label>
                            <select id="bookFiction">
                                <option value="Fiction" ${(book.fiction === true || book.fiction === 'Fiction') ? 'selected' : ''}>Fiction</option>
                                <option value="Non-Fiction" ${(book.fiction === false || book.fiction === 'Non-Fiction') ? 'selected' : ''}>Non-Fiction</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Rezension (anzeigen/bearbeiten) -->
                <div id="reviewDisplay" class="book-section">
                    <div class="section-header">
                        <h3>Rezension</h3>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleEditMode('review')">Bearbeiten</button>
                    </div>
                    <div class="review-display">
                        ${book.review ? `<div class="review-content">${convertMarkdownToHtml(book.review)}</div>` : '<p><em>Noch keine Rezension geschrieben.</em></p>'}
                    </div>
                </div>

                <!-- Rezension bearbeiten (versteckt) -->
                <div id="reviewEdit" class="book-section" style="display: none;">
                    <div class="section-header">
                        <h3>Rezension bearbeiten</h3>
                        <div>
                            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelEditMode('review')">Abbrechen</button>
                            <button type="button" class="btn btn-sm btn-info" onclick="toggleReviewPreview()">Vorschau</button>
                            <button type="button" class="btn btn-sm btn-primary" onclick="saveReview(${book.id})">Speichern</button>
                        </div>
                    </div>
                    <div class="review-editor">
                        <div id="reviewTextarea" class="form-group">
                            <label for="bookReview">Rezension</label>
                            <textarea id="bookReview" placeholder="Ihre Meinung zum Buch... (Markdown wird unterstützt)" rows="8">${book.review || ''}</textarea>
                            <small>Vollständiger Markdown-Support: **fett**, *kursiv*, ~~durchgestrichen~~, \`code\`, \`\`\`code-blöcke\`\`\`, # Überschriften, - Listen, [Links](url), > Zitate, --- Trennlinien</small>
                        </div>
                        <div id="reviewPreview" class="form-group" style="display: none;">
                            <label>Vorschau</label>
                            <div class="review-preview-content" style="border: 1px solid #ddd; padding: 15px; min-height: 200px; background: #f9f9f9; border-radius: 4px;">
                                <em>Vorschau wird hier angezeigt...</em>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Schließen</button>
                <button type="button" class="btn btn-danger" onclick="deleteBook(${book.id})">Löschen</button>
            </div>
        `;
    } else {
        // Neues Buch hinzufügen (ursprüngliches Formular)
        modalBody = `
            <form id="bookForm">
                <!-- ISBN Suche -->
                <div class="form-group">
                    <label for="bookISBN">ISBN (optional)</label>
                    <div class="isbn-buttons-group">
                        <button type="button" class="btn btn-primary" onclick="searchByISBN(event)">
                            <i class="fas fa-search"></i> Suchen
                        </button>
                        <button type="button" class="btn btn-secondary" id="scanBarcodeBtn" onclick="startBarcodeScanner()">
                            <i class="fas fa-barcode"></i> Scannen
                        </button>
                    </div>
                    <input type="text" id="bookISBN" placeholder="ISBN eingeben...">
                    <small>Buchdaten werden automatisch ausgefüllt</small>
                </div>

                <!-- Cover Upload für neues Buch -->
                <div class="form-group">
                    <label for="newBookCover">Cover hochladen (optional)</label>
                    <input type="file" id="newBookCover" accept="image/*" onchange="previewNewBookCover(this)">
                    <small>Unterstützte Formate: JPG, PNG, WebP</small>
                    <div id="coverErrorMessage" style="margin-top: 8px;"></div>
                    <div id="newBookCoverPreview" class="cover-preview" style="display: none;">
                        <img id="newBookPreviewImage" alt="Vorschau">
                    </div>
                </div>
                
                <div class="form-grid">
                    <div class="form-group">
                        <label for="bookTitle">Titel *</label>
                        <input type="text" id="bookTitle" value="${book.title || ''}" required>
                    </div>
                    <div class="form-group">
                        <label for="bookAuthor">Autor *</label>
                        <input type="text" id="bookAuthor" value="${book.author || ''}" required>
                    </div>
                    <div class="form-group">
                        <label for="bookGenre">Genre *</label>
                        <div class="autocomplete-container">
                            <input type="text" id="bookGenre" placeholder="Genre eingeben..." required>
                            <div id="genreSuggestions" class="autocomplete-suggestions"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="bookPages">Seiten *</label>
                        <input type="number" id="bookPages" value="${book.pages || ''}" required min="1">
                    </div>
                    <div class="form-group">
                        <label for="bookFormat">Format *</label>
                        <select id="bookFormat" required>
                            <option value="">Format wählen</option>
                            <option value="Hardcover" ${book.format === 'Hardcover' ? 'selected' : ''}>Hardcover</option>
                            <option value="Paperback" ${book.format === 'Paperback' ? 'selected' : ''}>Paperback</option>
                            <option value="eBook" ${book.format === 'eBook' ? 'selected' : ''}>eBook</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="bookPublisher">Verlag *</label>
                        <div class="autocomplete-container">
                            <input type="text" id="bookPublisher" placeholder="Verlag eingeben..." required>
                            <div id="publisherSuggestions" class="autocomplete-suggestions"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="bookPublishDate">Erscheinungsdatum *</label>
                        <input type="date" id="bookPublishDate" value="${book.publish_date ? book.publish_date.split('T')[0] : (book.publishDate ? book.publishDate.split('T')[0] : '')}" required>
                    </div>
                    <div class="form-group">
                        <label for="bookSeries">Reihe</label>
                        <input type="text" id="bookSeries" value="${book.series || ''}">
                    </div>
                    <div class="form-group">
                        <label for="bookVolume">Band</label>
                        <input type="text" id="bookVolume" value="${book.volume || ''}">
                    </div>
                    <div class="form-group">
                        <label for="bookStatus">Status</label>
                        <select id="bookStatus">
                            <option value="Ungelesen" ${(book.status === 'Ungelesen' || (!book.status && !(book.isRead || book.is_read))) ? 'selected' : ''}>Ungelesen</option>
                            <option value="Am Lesen" ${book.status === 'Am Lesen' ? 'selected' : ''}>Am Lesen</option>
                            <option value="Gelesen" ${(book.status === 'Gelesen' || (!book.status && (book.isRead || book.is_read))) ? 'selected' : ''}>Gelesen</option>
                        </select>
                    </div>
                </div>
                
                <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                    <button type="submit" class="btn btn-primary">Hinzufügen</button>
                </div>
            </form>
        `;
    }
    
    showModal(title, modalBody);
    
    // Genres und Verlage laden
    if (document.getElementById('bookGenre')) {
        setupGenreAutocomplete('bookGenre', book.genre);
    }
    if (document.getElementById('bookPublisher')) {
        setupPublisherAutocomplete('bookPublisher', book.publisher);
    }
    
    // Debug: Prüfe ISBN-Feld NACH dem Rendering
    if (isEdit) {
        setTimeout(() => {
            const isbnInput = document.getElementById('bookISBN');
            console.log('=== ISBN FIELD CHECK ===');
            console.log('[showBookModal] ISBN Input Element gefunden:', !!isbnInput);
            if (isbnInput) {
                console.log('[showBookModal] ISBN Input .value:', isbnInput.value);
                console.log('[showBookModal] ISBN Input .value Länge:', isbnInput.value.length);
                console.log('[showBookModal] ISBN Input getAttribute("value"):', isbnInput.getAttribute('value'));
                console.log('[showBookModal] Sollte sein (book.isbn):', book.isbn);
                console.log('[showBookModal] Input ist sichtbar?', isbnInput.offsetParent !== null);
                console.log('[showBookModal] Input parent display:', isbnInput.parentElement ? getComputedStyle(isbnInput.parentElement).display : 'N/A');
            } else {
                console.error('[showBookModal] ❌ ISBN Input Element NICHT gefunden!');
            }
            console.log('=== ISBN FIELD CHECK END ===');
        }, 100);
    }
    
    // Event-Listener für neues Buch
    if (!isEdit) {
        document.getElementById('bookForm').onsubmit = (e) => {
            e.preventDefault();
            createBook();
        };
    }
    
    // Event-Listener für Detailansicht
    if (isEdit) {
        setupDetailViewEvents(book);
        
        // Setup für Lesefortschritt mit Live-Berechnung
        const currentPageInput = document.getElementById('currentPage');
        const progressBar = document.querySelector('.progress-fill');
        const progressText = document.querySelector('.progress-text');
        
        if (currentPageInput) {
            currentPageInput.addEventListener('input', () => {
                updateProgressDisplay(currentPageInput.value, book.pages, progressBar, progressText);
            });
        }
        
        // Lade Fortschritt-Historie
        displayProgressHistory(book.id);
    }
}

// Hilfsfunktionen
async function loadGenresForSelect(selectId, selectedValue = '') {
    try {
        const genres = await apiCall('/genres');
        const select = document.getElementById(selectId);
        
        genres.forEach(genre => {
            const option = document.createElement('option');
            option.value = genre.name;
            option.textContent = genre.name;
            option.selected = genre.name === selectedValue;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Fehler beim Laden der Genres:', error);
    }
}

async function loadPublishersForSelect(selectId, selectedValue = '') {
    // Diese Funktion wird jetzt für das Autocomplete-System verwendet
    setupPublisherAutocomplete(selectId, selectedValue);
}

// Neues Publisher-Autocomplete-System
async function setupPublisherAutocomplete(inputId, initialValue = '') {
    const input = document.getElementById(inputId);
    if (!input) return;
    
    // Setze den initialen Wert
    if (initialValue) {
        input.value = initialValue;
    }
    
    // Hole alle Verlage für die Vorschläge
    let allPublishers = [];
    try {
        allPublishers = await apiCall('/publishers');
    } catch (error) {
        console.error('Fehler beim Laden der Verlage:', error);
    }
    
    // Suggestions Container finden
    let suggestionsContainer = document.getElementById('publisherSuggestions');
    if (!suggestionsContainer) {
        suggestionsContainer = document.getElementById('wishlistPublisherSuggestions');
    }
    if (!suggestionsContainer) {
        suggestionsContainer = document.getElementById('editWishlistPublisherSuggestions');
    }
    
    if (!suggestionsContainer) {
        console.error('Suggestions Container nicht gefunden für:', inputId);
        return;
    }
    
    // Event Listener für Input
    input.addEventListener('input', function(e) {
        const query = e.target.value.trim();
        showPublisherSuggestions(query, allPublishers, suggestionsContainer, input);
    });
    
    // Event Listener für Focus
    input.addEventListener('focus', function(e) {
        const query = e.target.value.trim();
        if (query.length > 0) {
            showPublisherSuggestions(query, allPublishers, suggestionsContainer, input);
        }
    });
    
    // Event Listener für das Schließen bei Klick außerhalb
    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !suggestionsContainer.contains(e.target)) {
            suggestionsContainer.classList.remove('show');
        }
    });
    
    // Keydown Event für Navigation
    input.addEventListener('keydown', function(e) {
        const suggestions = suggestionsContainer.querySelectorAll('.autocomplete-suggestion');
        const selected = suggestionsContainer.querySelector('.autocomplete-suggestion.selected');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            let next = selected ? selected.nextElementSibling : suggestions[0];
            if (next) {
                if (selected) selected.classList.remove('selected');
                next.classList.add('selected');
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            let prev = selected ? selected.previousElementSibling : suggestions[suggestions.length - 1];
            if (prev) {
                if (selected) selected.classList.remove('selected');
                prev.classList.add('selected');
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (selected) {
                input.value = selected.textContent.replace(' erstellen', '');
                suggestionsContainer.classList.remove('show');
            }
        } else if (e.key === 'Escape') {
            suggestionsContainer.classList.remove('show');
        }
    });
}

function showPublisherSuggestions(query, allPublishers, container, input) {
    container.innerHTML = '';
    
    if (!query || query.length < 1) {
        container.classList.remove('show');
        return;
    }
    
    // Filtere Verlage nach Eingabe (case-insensitive)
    const filteredPublishers = allPublishers.filter(publisher => 
        publisher.name.toLowerCase().includes(query.toLowerCase())
    );
    
    // Zeige passende Verlage
    filteredPublishers.forEach(publisher => {
        const suggestion = document.createElement('div');
        suggestion.className = 'autocomplete-suggestion';
        suggestion.textContent = publisher.name;
        suggestion.addEventListener('click', function() {
            input.value = publisher.name;
            container.classList.remove('show');
        });
        container.appendChild(suggestion);
    });
    
    // Zeige "Neu erstellen" Option wenn kein exakter Match
    const exactMatch = filteredPublishers.find(p => p.name.toLowerCase() === query.toLowerCase());
    if (!exactMatch && query.length > 0) {
        const createNew = document.createElement('div');
        createNew.className = 'autocomplete-suggestion create-new';
        createNew.innerHTML = `<i class="fas fa-plus"></i> "${query}" erstellen`;
        createNew.addEventListener('click', function() {
            input.value = query;
            container.classList.remove('show');
        });
        container.appendChild(createNew);
    }
    
    // Zeige Container wenn Vorschläge vorhanden
    if (container.children.length > 0) {
        container.classList.add('show');
    } else {
        container.classList.remove('show');
    }
}

// Neues Genre-Autocomplete-System (analog zu Publisher)
async function setupGenreAutocomplete(inputId, initialValue = '') {
    const input = document.getElementById(inputId);
    if (!input) return;
    
    // Setze den initialen Wert
    if (initialValue) {
        input.value = initialValue;
    }
    
    // Hole alle Genres für die Vorschläge
    let allGenres = [];
    try {
        allGenres = await apiCall('/genres');
    } catch (error) {
        console.error('Fehler beim Laden der Genres:', error);
    }
    
    // Suggestions Container finden
    let suggestionsContainer = document.getElementById('genreSuggestions');
    if (!suggestionsContainer) {
        suggestionsContainer = document.getElementById('wishlistGenreSuggestions');
    }
    if (!suggestionsContainer) {
        suggestionsContainer = document.getElementById('editWishlistGenreSuggestions');
    }
    
    if (!suggestionsContainer) {
        console.error('Genre Suggestions Container nicht gefunden für:', inputId);
        return;
    }
    
    // Event Listener für Input
    input.addEventListener('input', function(e) {
        const query = e.target.value.trim();
        showGenreSuggestions(query, allGenres, suggestionsContainer, input);
    });
    
    // Event Listener für Focus
    input.addEventListener('focus', function(e) {
        const query = e.target.value.trim();
        if (query.length > 0) {
            showGenreSuggestions(query, allGenres, suggestionsContainer, input);
        }
    });
    
    // Event Listener für das Schließen bei Klick außerhalb
    document.addEventListener('click', function(e) {
        if (!input.contains(e.target) && !suggestionsContainer.contains(e.target)) {
            suggestionsContainer.classList.remove('show');
        }
    });
    
    // Keydown Event für Navigation
    input.addEventListener('keydown', function(e) {
        const suggestions = suggestionsContainer.querySelectorAll('.autocomplete-suggestion');
        const selected = suggestionsContainer.querySelector('.autocomplete-suggestion.selected');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            let next = selected ? selected.nextElementSibling : suggestions[0];
            if (next) {
                if (selected) selected.classList.remove('selected');
                next.classList.add('selected');
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            let prev = selected ? selected.previousElementSibling : suggestions[suggestions.length - 1];
            if (prev) {
                if (selected) selected.classList.remove('selected');
                prev.classList.add('selected');
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (selected) {
                input.value = selected.textContent.replace(' erstellen', '');
                suggestionsContainer.classList.remove('show');
            }
        } else if (e.key === 'Escape') {
            suggestionsContainer.classList.remove('show');
        }
    });
}

function showGenreSuggestions(query, allGenres, container, input) {
    container.innerHTML = '';
    
    if (!query || query.length < 1) {
        container.classList.remove('show');
        return;
    }
    
    // Filtere Genres nach Eingabe (case-insensitive)
    const filteredGenres = allGenres.filter(genre => 
        genre.name.toLowerCase().includes(query.toLowerCase())
    );
    
    // Zeige passende Genres
    filteredGenres.forEach(genre => {
        const suggestion = document.createElement('div');
        suggestion.className = 'autocomplete-suggestion';
        suggestion.textContent = genre.name;
        suggestion.addEventListener('click', function() {
            input.value = genre.name;
            container.classList.remove('show');
        });
        container.appendChild(suggestion);
    });
    
    // Zeige "Neu erstellen" Option wenn kein exakter Match
    const exactMatch = filteredGenres.find(g => g.name.toLowerCase() === query.toLowerCase());
    if (!exactMatch && query.length > 0) {
        const createNew = document.createElement('div');
        createNew.className = 'autocomplete-suggestion create-new';
        createNew.innerHTML = `<i class="fas fa-plus"></i> "${query}" erstellen`;
        createNew.addEventListener('click', function() {
            input.value = query;
            container.classList.remove('show');
        });
        container.appendChild(createNew);
    }
    
    // Zeige Container wenn Vorschläge vorhanden
    if (container.children.length > 0) {
        container.classList.add('show');
    } else {
        container.classList.remove('show');
    }
}

// Genre und Publisher Management
async function deleteGenre(genreId) {
    if (!confirm('Sind Sie sicher, dass Sie dieses Genre löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/genres/${genreId}`, {
            method: 'DELETE'
        });
        
        loadGenreList();
        showMessage(null, 'Genre erfolgreich gelöscht!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Löschen: ' + error.message, 'error');
    }
}

async function deletePublisher(publisherId) {
    if (!confirm('Sind Sie sicher, dass Sie diesen Verlag löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/publishers/${publisherId}`, {
            method: 'DELETE'
        });
        
        loadPublisherList();
        showMessage(null, 'Verlag erfolgreich gelöscht!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Löschen: ' + error.message, 'error');
    }
}

// Statistiken
async function loadStatistics() {
    try {
        const stats = await apiCall('/stats');
        const statisticsContent = document.getElementById('statisticsContent');
        
        // Berechne gelesene Seiten - hole alle Bücher um korrekte Statistik zu erhalten
        let totalPagesRead = 0;
        try {
            const allBooks = await apiCall('/books');
            totalPagesRead = allBooks.reduce((sum, book) => {
                if (book.status === 'Gelesen') {
                    // Vollständig gelesene Bücher: alle Seiten zählen
                    return sum + (book.pages || 0);
                } else if (book.status === 'Am Lesen') {
                    // Bücher die gerade gelesen werden: nur Fortschritt zählen
                    return sum + (book.reading_progress || book.readingProgress || 0);
                }
                return sum;
            }, 0);
        } catch (error) {
            console.error('Fehler beim Berechnen der gelesenen Seiten:', error);
        }
        
        statisticsContent.innerHTML = `
            <div class="stats-overview">
                <div class="stat-card">
                    <i class="fas fa-books stat-icon"></i>
                    <h3>Bücher Gesamt</h3>
                    <div class="stat-number">${stats.totalBooks || 0}</div>
                </div>
                <div class="stat-card">
                    <i class="fas fa-check-circle stat-icon"></i>
                    <h3>Gelesen</h3>
                    <div class="stat-number">${stats.readBooks || 0}</div>
                </div>
                <div class="stat-card">
                    <i class="fas fa-clock stat-icon"></i>
                    <h3>Ungelesen</h3>
                    <div class="stat-number">${(stats.totalBooks || 0) - (stats.readBooks || 0)}</div>
                </div>
                <div class="stat-card">
                    <i class="fas fa-file-alt stat-icon"></i>
                    <h3>Gelesene Seiten</h3>
                    <div class="stat-number">${totalPagesRead}</div>
                </div>
                <div class="stat-card">
                    <i class="fas fa-quote-right stat-icon"></i>
                    <h3>Zitate</h3>
                    <div class="stat-number">${stats.totalQuotes || 0}</div>
                </div>
            </div>
            
            <div class="stats-details">
                <div class="stats-section">
                    <h3>Bücher nach Genre</h3>
                    <div class="stats-list" id="genreStats">
                        <p>Lade Genre-Statistiken...</p>
                    </div>
                </div>
                
                <div class="stats-section">
                    <h3>Bücher nach Verlag</h3>
                    <div class="stats-list" id="publisherStats">
                        <p>Lade Verlag-Statistiken...</p>
                    </div>
                </div>
                
                <div class="stats-section">
                    <h3>Leseziel</h3>
                    <div class="reading-goal-section" id="readingGoalStats">
                        <p>Lade Leseziel...</p>
                    </div>
                </div>
            </div>
        `;
        
        // Lade detaillierte Statistiken
        loadGenreStats();
        loadPublisherStats();
        loadReadingGoalStats();
    } catch (error) {
        console.error('Fehler beim Laden der Statistiken:', error);
        document.getElementById('statisticsContent').innerHTML = '<p>Fehler beim Laden der Statistiken.</p>';
    }
}

async function loadGenreStats() {
    try {
        const genreStats = await apiCall('/stats/genres');
        const genreStatsEl = document.getElementById('genreStats');
        
        if (genreStats && genreStats.length > 0) {
            genreStatsEl.innerHTML = genreStats.map(genre => 
                `<div class="stat-item">
                    <span class="stat-label">${escapeHtml(genre.name)}</span>
                    <span class="stat-value">${genre.count} Bücher</span>
                </div>`
            ).join('');
        } else {
            genreStatsEl.innerHTML = '<p>Keine Genre-Statistiken verfügbar.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Genre-Statistiken:', error);
        document.getElementById('genreStats').innerHTML = '<p>Fehler beim Laden der Genre-Statistiken.</p>';
    }
}

async function loadPublisherStats() {
    try {
        const publisherStats = await apiCall('/stats/publishers');
        const publisherStatsEl = document.getElementById('publisherStats');
        
        if (publisherStats && publisherStats.length > 0) {
            publisherStatsEl.innerHTML = publisherStats.map(publisher => 
                `<div class="stat-item">
                    <span class="stat-label">${escapeHtml(publisher.name)}</span>
                    <span class="stat-value">${publisher.count} Bücher</span>
                </div>`
            ).join('');
        } else {
            publisherStatsEl.innerHTML = '<p>Keine Verlag-Statistiken verfügbar.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Verlag-Statistiken:', error);
        document.getElementById('publisherStats').innerHTML = '<p>Fehler beim Laden der Verlag-Statistiken.</p>';
    }
}

async function loadReadingGoalStats() {
    try {
        const goal = await apiCall('/reading-goal');
        const goalStatsEl = document.getElementById('readingGoalStats');
        
        if (goal && goal.enabled) {
            const percentage = Math.min((goal.current / goal.target) * 100, 100);
            goalStatsEl.innerHTML = `
                <div class="reading-goal-progress">
                    <div class="goal-info">
                        <span>Ziel: ${goal.target} Bücher pro Jahr</span>
                        <span>Gelesen: ${goal.current} Bücher</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${percentage}%"></div>
                    </div>
                    <div class="goal-percentage">${percentage.toFixed(1)}% erreicht</div>
                </div>
            `;
        } else {
            goalStatsEl.innerHTML = '<p>Kein Leseziel gesetzt.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden des Leseziels:', error);
        document.getElementById('readingGoalStats').innerHTML = '<p>Fehler beim Laden des Leseziels.</p>';
    }
}

// Settings
async function loadSettings() {
    try {
        const settingsContent = document.getElementById('settingsContent');
        if (!settingsContent) {
            console.error('Settings content element not found');
            return;
        }
        
        settingsContent.innerHTML = `
            <div class="settings-section">
                <h3>Darstellung</h3>
                <div class="theme-toggle-container">
                    <span class="theme-toggle-label">
                        <i class="fas fa-moon"></i> Dark Mode
                    </span>
                    <label class="theme-toggle">
                        <input type="checkbox" id="themeToggle">
                        <span class="theme-slider"></span>
                    </label>
                </div>
            </div>
            
            <div class="settings-section">
                <h3>Leseziel</h3>
                <div class="reading-goal-settings" id="readingGoalSettings">
                    <div class="form-group">
                        <label for="readingGoalType">Leseziel-Status</label>
                        <select id="readingGoalType">
                            <option value="disabled">Deaktiviert</option>
                            <option value="enabled">Aktiviert</option>
                        </select>
                    </div>
                    <div class="form-group" id="goalTargetGroup" style="display: none;">
                        <label for="readingGoalTarget">Bücher pro Jahr</label>
                        <input type="number" id="readingGoalTarget" min="1" max="365" value="12">
                    </div>
                    <button class="btn btn-primary" onclick="saveReadingGoal()">Leseziel speichern</button>
                </div>
            </div>
            
            <div class="settings-section">
                <h3>Genres verwalten</h3>
                <div class="genre-management">
                    <div class="info-box">
                        <p><strong>Hinweis:</strong> Neue Genres werden automatisch erstellt, wenn Sie sie beim Hinzufügen von Büchern oder Wunschlisten-Einträgen eingeben.</p>
                    </div>
                    <div class="genre-list" id="genreList">
                        <p>Lade Genres...</p>
                    </div>
                </div>
            </div>
            
            <div class="settings-section">
                <h3>Verlage verwalten</h3>
                <div class="publisher-management">
                    <div class="info-box">
                        <p><strong>Hinweis:</strong> Neue Verlage werden automatisch erstellt, wenn Sie sie beim Hinzufügen von Büchern oder Wunschlisten-Einträgen eingeben.</p>
                    </div>
                    <div class="publisher-list" id="publisherList">
                        <p>Lade Verlage...</p>
                    </div>
                </div>
            </div>
        `;
        
        // Initialize theme toggle after loading settings
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            // Setze Initial-State basierend auf aktuellem Theme
            const currentTheme = getTheme();
            themeToggle.checked = currentTheme === 'dark';
            
            themeToggle.addEventListener('change', (e) => {
                const newTheme = e.target.checked ? 'dark' : 'light';
                setTheme(newTheme);
                localStorage.setItem('readingDiaryTheme', newTheme);
            });
        }
        
        // Load current reading goal
        loadCurrentReadingGoal();
        loadGenreList();
        loadPublisherList();
        
        // Event listener for reading goal type
        document.getElementById('readingGoalType').addEventListener('change', function() {
            const targetGroup = document.getElementById('goalTargetGroup');
            targetGroup.style.display = this.value === 'enabled' ? 'block' : 'none';
        });
        
    } catch (error) {
        console.error('Fehler beim Laden der Einstellungen:', error);
        if (document.getElementById('settingsContent')) {
            document.getElementById('settingsContent').innerHTML = '<p>Fehler beim Laden der Einstellungen.</p>';
        }
    }
}

async function loadCurrentReadingGoal() {
    try {
        const goal = await apiCall('/reading-goal');
        const typeSelect = document.getElementById('readingGoalType');
        const targetInput = document.getElementById('readingGoalTarget');
        const targetGroup = document.getElementById('goalTargetGroup');
        
        if (typeSelect && targetInput && targetGroup) {
            if (goal && goal.enabled) {
                typeSelect.value = 'enabled';
                targetInput.value = goal.target || 12;
                targetGroup.style.display = 'block';
            } else {
                typeSelect.value = 'disabled';
                targetInput.value = 12;
                targetGroup.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Fehler beim Laden des aktuellen Leseziels:', error);
    }
}

async function loadGenreList() {
    try {
        const genres = await apiCall('/genres');
        const genreListEl = document.getElementById('genreList');
        
        if (genres && genres.length > 0) {
            genreListEl.innerHTML = genres.map(genre => 
                `<div class="list-item">
                    <span class="item-name">${escapeHtml(genre.name)}</span>
                    <button class="btn btn-danger btn-sm" onclick="deleteGenre(${genre.id})">
                        <i class="fas fa-trash"></i> Löschen
                    </button>
                </div>`
            ).join('');
        } else {
            genreListEl.innerHTML = '<p>Keine Genres gefunden.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Genres:', error);
        document.getElementById('genreList').innerHTML = '<p>Fehler beim Laden der Genres.</p>';
    }
}

async function loadPublisherList() {
    try {
        const publishers = await apiCall('/publishers');
        const publisherListEl = document.getElementById('publisherList');
        
        if (publishers && publishers.length > 0) {
            publisherListEl.innerHTML = publishers.map(publisher => 
                `<div class="list-item">
                    <span class="item-name">${escapeHtml(publisher.name)}</span>
                    <button class="btn btn-danger btn-sm" onclick="deletePublisher(${publisher.id})">
                        <i class="fas fa-trash"></i> Löschen
                    </button>
                </div>`
            ).join('');
        } else {
            publisherListEl.innerHTML = '<p>Keine Verlage gefunden.</p>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Verlage:', error);
        document.getElementById('publisherList').innerHTML = '<p>Fehler beim Laden der Verlage.</p>';
    }
}

async function saveReadingGoal() {
    try {
        const typeSelect = document.getElementById('readingGoalType');
        const targetInput = document.getElementById('readingGoalTarget');
        
        if (!typeSelect || !targetInput) {
            showMessage(null, 'Formular-Elemente nicht gefunden.', 'error');
            return;
        }
        
        const enabled = typeSelect.value === 'enabled';
        const target = enabled ? parseInt(targetInput.value) || 12 : 12;
        
        console.log('Speichere Leseziel:', { enabled, target });
        
        const response = await apiCall('/reading-goal', {
            method: 'PUT',
            body: { enabled, target }
        });
        
        console.log('Leseziel Antwort:', response);
        
        showMessage(null, 'Leseziel erfolgreich gespeichert!', 'success');
        
        // Refresh reading goal display
        setTimeout(() => {
            loadCurrentReadingGoal();
            loadReadingGoalProgress();
        }, 500);
        
    } catch (error) {
        console.error('Fehler beim Speichern:', error);
        showMessage(null, 'Fehler beim Speichern des Leseziels: ' + error.message, 'error');
    }
}

// Modal und UI Funktionen
function showModal(title, body) {
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    
    modalTitle.textContent = title;
    modalBody.innerHTML = body;
    modal.style.display = 'flex';
}

function closeModal() {
    const modal = document.getElementById('modal');
    modal.style.display = 'none';
}

// Setup-Funktionen für Detail-View
function setupDetailViewEvents(book) {
    // Rating Events
    setupRatingEvents();
    
    // Spannung Slider Event
    const tensionSlider = document.getElementById('bookTension');
    const tensionValue = document.getElementById('tensionValue');
    if (tensionSlider && tensionValue) {
        tensionSlider.addEventListener('input', () => {
            tensionValue.textContent = tensionSlider.value;
        });
    }
}

// Progress History anzeigen
async function displayProgressHistory(bookId) {
    const historyDiv = document.getElementById('progressHistory');
    if (!historyDiv) return;
    
    try {
        historyDiv.innerHTML = '<p><em>Lade Fortschritt-Historie...</em></p>';
        
        // Lade Historie vom Backend
        const response = await apiCall(`/books/${bookId}/progress-history`);
        
        if (response && response.length > 0) {
            historyDiv.innerHTML = `
                <h4>Fortschritt-Historie</h4>
                <div class="progress-history-list">
                    ${response.map(entry => {
                        const date = new Date(entry.date);
                        const formattedDate = date.toLocaleDateString('de-DE');
                        const formattedTime = date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
                        const changeText = entry.change > 0 ? `+${entry.change}` : entry.change.toString();
                        const changeClass = entry.change > 0 ? 'progress-positive' : (entry.change < 0 ? 'progress-negative' : 'progress-zero');
                        
                        return `
                        <div class="progress-history-item ${changeClass}">
                            <div class="progress-date">
                                <span class="date">${formattedDate}</span>
                                <span class="time">${formattedTime}</span>
                            </div>
                            <div class="progress-info">
                                <span class="progress-pages">Seite ${entry.page}</span>
                                <span class="progress-change">${changeText} Seiten</span>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            `;
        } else {
            // Fallback: Zeige aktuellen Stand
            const currentPage = document.getElementById('currentPage')?.value || 0;
            const now = new Date();
            const formattedDate = now.toLocaleDateString('de-DE');
            const formattedTime = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
            
            historyDiv.innerHTML = `
                <h4>Fortschritt-Historie</h4>
                <div class="progress-history-list">
                    <div class="progress-history-item progress-zero">
                        <div class="progress-date">
                            <span class="date">${formattedDate}</span>
                            <span class="time">${formattedTime}</span>
                        </div>
                        <div class="progress-info">
                            <span class="progress-pages">Seite ${currentPage}</span>
                            <span class="progress-change">Aktueller Stand</span>
                        </div>
                    </div>
                </div>
                <p style="margin-top: 12px; font-size: 12px; color: #666;"><em>Historie wird beim nächsten Fortschritt-Update erstellt.</em></p>
            `;
        }
    } catch (error) {
        console.error('Fehler beim Laden der Fortschritt-Historie:', error);
        historyDiv.innerHTML = `
            <h4>Fortschritt-Historie</h4>
            <p style="color: #666; font-style: italic;">Historie konnte nicht geladen werden.</p>
        `;
    }
}

// Progress speichern
async function saveProgress(bookId) {
    const currentPage = parseInt(document.getElementById('currentPage').value) || 0;
    
    try {
        showMessage(null, 'Speichere Fortschritt...', 'info');
        
        const bookData = {
            reading_progress: currentPage
        };
        
        const response = await apiCall(`/books/${bookId}`, {
            method: 'PUT',
            body: bookData
        });
        
        showMessage(null, 'Fortschritt erfolgreich gespeichert.', 'success');
        
        // Aktualisiere die Anzeige
        const book = response;
        const pages = book.pages || parseInt(document.getElementById('currentPage').getAttribute('max')) || 100;
        const progressPercent = pages > 0 ? Math.round((currentPage / pages) * 100) : 0;
        const progressBar = document.querySelector('.progress-fill');
        const progressText = document.querySelector('.progress-text');
        
        if (progressBar) progressBar.style.width = `${progressPercent}%`;
        if (progressText) progressText.textContent = `${progressPercent}% gelesen`;
        
        // Lade Fortschritt-Historie neu
        displayProgressHistory(bookId);
        
    } catch (error) {
        console.error('Error saving progress:', error);
        showMessage(null, 'Fehler beim Speichern des Fortschritts.', 'error');
    }
}

// Review Preview Toggle
function toggleReviewPreview() {
    const textareaDiv = document.getElementById('reviewTextarea');
    const previewDiv = document.getElementById('reviewPreview');
    const reviewTextarea = document.getElementById('bookReview');
    const previewContent = previewDiv.querySelector('.review-preview-content');
    
    if (previewDiv.style.display === 'none') {
        // Zeige Vorschau
        const markdownContent = reviewTextarea.value;
        previewContent.innerHTML = convertMarkdownToHtml(markdownContent) || '<em>Keine Inhalte vorhanden</em>';
        
        textareaDiv.style.display = 'none';
        previewDiv.style.display = 'block';
    } else {
        // Zeige Textarea
        textareaDiv.style.display = 'block';
        previewDiv.style.display = 'none';
    }
}

// Fehlende Funktionen für das Modal-System
function toggleEditMode(section) {
    const displayDiv = document.getElementById(`${section}Display`);
    const editDiv = document.getElementById(`${section}Edit`);
    
    if (displayDiv && editDiv) {
        displayDiv.style.display = 'none';
        editDiv.style.display = 'block';
        
        // Wenn basicInfo bearbeitet wird, prüfe ob ISBN aus der Anzeige übernommen werden muss
        if (section === 'basicInfo') {
            // Hole ISBN aus dem Display-Text
            const bookInfoGrid = displayDiv.querySelector('.book-info-grid');
            if (bookInfoGrid) {
                const isbnDiv = Array.from(bookInfoGrid.querySelectorAll('div')).find(div => 
                    div.textContent.includes('ISBN:')
                );
                if (isbnDiv) {
                    const isbnText = isbnDiv.textContent.replace('ISBN:', '').trim();
                    const isbnInput = document.getElementById('bookISBN');
                    if (isbnInput && isbnText) {
                        isbnInput.value = isbnText;
                        console.log('[toggleEditMode] ISBN gesetzt:', isbnText);
                    }
                }
            }
        }
    }
}

function cancelEditMode(section) {
    const displayDiv = document.getElementById(`${section}Display`);
    const editDiv = document.getElementById(`${section}Edit`);
    
    if (displayDiv && editDiv) {
        displayDiv.style.display = 'block';
        editDiv.style.display = 'none';
    }
}

function setupRatingEvents() {
    const ratingElements = document.querySelectorAll('.rating');
    
    ratingElements.forEach(rating => {
        const stars = rating.querySelectorAll('.star');
        const ratingType = rating.dataset.rating;
        
        stars.forEach((star, index) => {
            star.addEventListener('click', () => {
                const value = index + 1;
                rating.dataset.value = value;
                
                // Update star display
                stars.forEach((s, i) => {
                    s.classList.toggle('active', i < value);
                    
                    // Update spice level content
                    if (ratingType === 'spice') {
                        s.textContent = i < value ? '🌶️' : '❌';
                    }
                });
                
                // Show save button
                const saveBtn = document.getElementById('saveRatingsBtn');
                if (saveBtn) {
                    saveBtn.style.display = 'inline-block';
                }
            });
            
            // Add hover effect for spice rating
            if (ratingType === 'spice') {
                star.addEventListener('mouseenter', () => {
                    const hoverValue = index + 1;
                    stars.forEach((s, i) => {
                        s.textContent = i < hoverValue ? '🌶️' : '❌';
                    });
                });
                
                rating.addEventListener('mouseleave', () => {
                    const currentValue = parseInt(rating.dataset.value) || 0;
                    stars.forEach((s, i) => {
                        s.textContent = i < currentValue ? '🌶️' : '❌';
                    });
                });
            }
        });
    });
}

// ISBN Suchfunktionen
async function searchByISBN(evt) {
    const isbnInput = document.getElementById('bookISBN');
    const isbn = isbnInput.value.trim().replace(/[^0-9X]/gi, '');
    
    if (!isbn) {
        showMessage(null, 'Bitte geben Sie eine ISBN ein.', 'error');
        return;
    }
    
    // Deaktiviere Button und zeige Lade-Indikator (wenn von Button aufgerufen)
    let searchBtn = null;
    let originalBtnText = '';
    
    if (evt && evt.target) {
        searchBtn = evt.target;
        originalBtnText = searchBtn.innerHTML;
        searchBtn.disabled = true;
        searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Lädt...';
    }
    
    isbnInput.disabled = true;
    
    // Zeige immer eine Ladeanzeige, auch wenn vom Scanner aufgerufen
    const loadingMessage = showMessage(null, '<i class="fas fa-spinner fa-spin"></i> Lade Buchdaten...', 'info');
    
    try {
        const bookData = await apiCall(`/isbn/${isbn}`);
        
        if (!bookData || !bookData.title) {
            throw new Error('Keine Buchdaten gefunden');
        }
        
        // Fülle die Formularfelder aus
        if (bookData.title) document.getElementById('bookTitle').value = bookData.title;
        if (bookData.author) document.getElementById('bookAuthor').value = bookData.author;
        if (bookData.genre) {
            document.getElementById('bookGenre').value = bookData.genre;
            // Trigger autocomplete update
            if (typeof setupGenreAutocomplete === 'function') {
                setupGenreAutocomplete('bookGenre', bookData.genre);
            }
        }
        if (bookData.publisher) {
            document.getElementById('bookPublisher').value = bookData.publisher;
            // Trigger autocomplete update
            if (typeof setupPublisherAutocomplete === 'function') {
                setupPublisherAutocomplete('bookPublisher', bookData.publisher);
            }
        }
        if (bookData.publish_date) {
            // Format date for input field (YYYY-MM-DD)
            const date = bookData.publish_date.split('T')[0];
            document.getElementById('bookPublishDate').value = date;
        }
        if (bookData.pages) document.getElementById('bookPages').value = bookData.pages;
        
        // Show cover preview if available (but don't download yet)
        let hasCover = false;
        if (bookData.cover_image_url) {
            const previewDiv = document.getElementById('newBookCoverPreview');
            const previewImg = document.getElementById('newBookPreviewImage');
            if (previewDiv && previewImg) {
                // Show loading spinner
                previewDiv.innerHTML = '<div class="cover-loading"><i class="fas fa-spinner fa-spin"></i><br>Lade Cover...</div>';
                previewDiv.style.display = 'block';
                
                // Create new image to load
                const img = new Image();
                img.onload = function() {
                    previewDiv.innerHTML = '';
                    previewImg.src = bookData.cover_image_url;
                    previewDiv.appendChild(previewImg);
                    // Store cover URL for download when saving
                    previewDiv.dataset.coverUrl = bookData.cover_image_url;
                    previewDiv.dataset.isbnCover = 'true';
                    hasCover = true;
                    // Entferne Fehlermeldung falls vorhanden
                    const errorDiv = document.getElementById('coverErrorMessage');
                    if (errorDiv) errorDiv.innerHTML = '';
                };
                img.onerror = function() {
                    console.warn('[ISBN] Cover konnte nicht geladen werden:', bookData.cover_image_url);
                    // Verstecke Preview
                    previewDiv.style.display = 'none';
                    previewDiv.innerHTML = '';
                    // Zeige Fehlermeldung unter "Unterstützte Formate"
                    const errorDiv = document.getElementById('coverErrorMessage');
                    if (errorDiv) {
                        errorDiv.innerHTML = '<div style="color: #ef4444; font-size: 14px;"><i class="fas fa-exclamation-triangle"></i> Cover konnte nicht geladen werden</div>';
                    }
                };
                img.src = bookData.cover_image_url;
            }
        } else {
            // Kein Cover vorhanden - zeige Meldung
            const errorDiv = document.getElementById('coverErrorMessage');
            if (errorDiv) {
                errorDiv.innerHTML = '<div style="color: #f59e0b; font-size: 14px;"><i class="fas fa-info-circle"></i> Kein Cover verfügbar</div>';
            }
        }
        
        // Entferne alte Fehlermeldung falls vorhanden
        const oldError = isbnInput.parentElement.querySelector('.isbn-error');
        if (oldError) oldError.remove();
    } catch (error) {
        console.error('ISBN Suche Fehler:', error);
        
        // Zeige Fehler unter dem ISBN-Feld
        let errorDiv = isbnInput.parentElement.querySelector('.isbn-error');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'isbn-error';
            errorDiv.style.cssText = 'color: #ef4444; font-size: 14px; margin-top: 8px;';
            isbnInput.parentElement.appendChild(errorDiv);
        }
        errorDiv.textContent = '❌ Die eingegebene ISBN konnte nicht gefunden werden. Bitte überprüfen Sie die ISBN oder geben Sie die Daten manuell ein.';
        
        showMessage(document.getElementById('addBookModal'), '❌ ISBN nicht gefunden', 'error');
    } finally {
        // Aktiviere Button wieder (wenn verwendet)
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerHTML = originalBtnText;
        }
        isbnInput.disabled = false;
    }
}

async function searchByISBNWishlist(evt) {
    const isbnInput = document.getElementById('wishlistISBN');
    const isbn = isbnInput.value.trim().replace(/[^0-9X]/gi, '');
    
    if (!isbn) {
        showMessage(null, 'Bitte geben Sie eine ISBN ein.', 'error');
        return;
    }
    
    // Deaktiviere Button und zeige Lade-Indikator (wenn von Button aufgerufen)
    let searchBtn = null;
    let originalBtnText = '';
    
    if (evt && evt.target) {
        searchBtn = evt.target;
        originalBtnText = searchBtn.innerHTML;
        searchBtn.disabled = true;
        searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Lädt...';
    }
    
    isbnInput.disabled = true;
    
    // Zeige immer eine Ladeanzeige, auch wenn vom Scanner aufgerufen
    const loadingMessage = showMessage(null, '<i class="fas fa-spinner fa-spin"></i> Lade Buchdaten...', 'info');
    
    try {
        const bookData = await apiCall(`/isbn/${isbn}`);
        
        if (!bookData || !bookData.title) {
            throw new Error('Keine Buchdaten gefunden');
        }
        
        // Fülle die Formularfelder aus
        if (bookData.title) document.getElementById('wishlistTitle').value = bookData.title;
        if (bookData.author) document.getElementById('wishlistAuthor').value = bookData.author;
        if (bookData.genre) {
            document.getElementById('wishlistGenre').value = bookData.genre;
            if (typeof setupGenreAutocomplete === 'function') {
                setupGenreAutocomplete('wishlistGenre', bookData.genre);
            }
        }
        if (bookData.publisher) {
            document.getElementById('wishlistPublisher').value = bookData.publisher;
            if (typeof setupPublisherAutocomplete === 'function') {
                setupPublisherAutocomplete('wishlistPublisher', bookData.publisher);
            }
        }
        if (bookData.publish_date) {
            // Format date for input field (YYYY-MM-DD)
            const date = bookData.publish_date.split('T')[0];
            document.getElementById('wishlistPublishDate').value = date;
        }
        if (bookData.pages) document.getElementById('wishlistPages').value = bookData.pages;
        
        // Show cover preview if available (but don't download yet)
        let hasCover = false;
        if (bookData.cover_image_url) {
            const previewDiv = document.getElementById('newWishlistCoverPreview');
            const previewImg = document.getElementById('newWishlistPreviewImage');
            if (previewDiv && previewImg) {
                // Show loading spinner
                previewDiv.innerHTML = '<div class="cover-loading"><i class="fas fa-spinner fa-spin"></i><br>Lade Cover...</div>';
                previewDiv.style.display = 'block';
                
                // Create new image to load
                const img = new Image();
                img.onload = function() {
                    previewDiv.innerHTML = '';
                    previewImg.src = bookData.cover_image_url;
                    previewDiv.appendChild(previewImg);
                    // Store cover URL for download when saving
                    previewDiv.dataset.coverUrl = bookData.cover_image_url;
                    previewDiv.dataset.isbnCover = 'true';
                    hasCover = true;
                    // Entferne Fehlermeldung falls vorhanden
                    const errorDiv = document.getElementById('wishlistCoverErrorMessage');
                    if (errorDiv) errorDiv.innerHTML = '';
                };
                img.onerror = function() {
                    console.warn('[ISBN Wishlist] Cover konnte nicht geladen werden:', bookData.cover_image_url);
                    // Verstecke Preview
                    previewDiv.style.display = 'none';
                    previewDiv.innerHTML = '';
                    // Zeige Fehlermeldung unter "Unterstützte Formate"
                    const errorDiv = document.getElementById('wishlistCoverErrorMessage');
                    if (errorDiv) {
                        errorDiv.innerHTML = '<div style="color: #ef4444; font-size: 14px;"><i class="fas fa-exclamation-triangle"></i> Cover konnte nicht geladen werden</div>';
                    }
                };
                img.src = bookData.cover_image_url;
            }
        } else {
            // Kein Cover vorhanden - zeige Meldung
            const errorDiv = document.getElementById('wishlistCoverErrorMessage');
            if (errorDiv) {
                errorDiv.innerHTML = '<div style="color: #f59e0b; font-size: 14px;"><i class="fas fa-info-circle"></i> Kein Cover verfügbar</div>';
            }
        }
        
        // Entferne alte Fehlermeldung falls vorhanden
        const oldError = isbnInput.parentElement.querySelector('.isbn-error');
        if (oldError) oldError.remove();
    } catch (error) {
        console.error('ISBN Suche Fehler:', error);
        
        // Zeige Fehler unter dem ISBN-Feld
        let errorDiv = isbnInput.parentElement.querySelector('.isbn-error');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'isbn-error';
            errorDiv.style.cssText = 'color: #ef4444; font-size: 14px; margin-top: 8px;';
            isbnInput.parentElement.appendChild(errorDiv);
        }
        errorDiv.textContent = '❌ Die eingegebene ISBN konnte nicht gefunden werden. Bitte überprüfen Sie die ISBN oder geben Sie die Daten manuell ein.';
        
        showMessage(document.getElementById('addWishlistModal'), '❌ ISBN nicht gefunden', 'error');
    } finally {
        // Aktiviere Button wieder (wenn verwendet)
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerHTML = originalBtnText;
        }
        isbnInput.disabled = false;
    }
}

// ISBN Suche für Bearbeitungsformular
async function searchByISBNEdit(evt, bookId) {
    const isbnInput = document.getElementById('bookISBN');
    const isbn = isbnInput.value.trim().replace(/[^0-9X]/gi, '');
    
    if (!isbn) {
        showMessage(null, 'Bitte geben Sie eine ISBN ein.', 'error');
        return;
    }
    
    // Deaktiviere Button und zeige Lade-Indikator
    let searchBtn = null;
    let originalBtnText = '';
    
    if (evt && evt.target) {
        searchBtn = evt.target;
        originalBtnText = searchBtn.innerHTML;
        searchBtn.disabled = true;
        searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Lädt...';
    }
    
    isbnInput.disabled = true;
    
    // Zeige immer eine Ladeanzeige, auch wenn vom Scanner aufgerufen
    const loadingMessage = showMessage(null, '<i class="fas fa-spinner fa-spin"></i> Lade Buchdaten...', 'info');
    
    // Debug: Prüfe Auth-Status
    console.log('[searchByISBNEdit] currentToken:', currentToken ? 'VORHANDEN (' + currentToken.length + ' chars)' : 'FEHLT!');
    console.log('[searchByISBNEdit] currentServerUrl:', currentServerUrl);
    console.log('[searchByISBNEdit] Vollständige URL:', `${currentServerUrl}/api/isbn/${isbn}`);
    
    if (!currentToken) {
        console.error('[searchByISBNEdit] FEHLER: Kein Token vorhanden!');
        showMessage(null, 'Authentifizierungsfehler. Bitte neu einloggen.', 'error');
        isbnInput.disabled = false;
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerHTML = originalBtnText;
        }
        return;
    }
    
    try {
        const bookData = await apiCall(`/isbn/${isbn}`);
        
        if (!bookData || !bookData.title) {
            throw new Error('Keine Buchdaten gefunden');
        }
        
        // Fülle die Formularfelder aus
        if (bookData.title) document.getElementById('bookTitle').value = bookData.title;
        if (bookData.author) document.getElementById('bookAuthor').value = bookData.author;
        if (bookData.genre) {
            document.getElementById('bookGenre').value = bookData.genre;
            if (typeof setupGenreAutocomplete === 'function') {
                setupGenreAutocomplete('bookGenre', bookData.genre);
            }
        }
        if (bookData.publisher) {
            document.getElementById('bookPublisher').value = bookData.publisher;
            if (typeof setupPublisherAutocomplete === 'function') {
                setupPublisherAutocomplete('bookPublisher', bookData.publisher);
            }
        }
        if (bookData.publish_date) {
            const date = bookData.publish_date.split('T')[0];
            document.getElementById('bookPublishDate').value = date;
        }
        if (bookData.pages) document.getElementById('bookPages').value = bookData.pages;
        
        // Aktualisiere Cover-Preview wenn verfügbar
        let hasCover = false;
        if (bookData.cover_image_url) {
            // Speichere Cover-Daten global (funktioniert immer, auch auf Mobile)
            editModeCoverData = {
                coverUrl: bookData.cover_image_url,
                isbn: isbn
            };
            console.log('[ISBN Edit] Cover-Daten global gespeichert:', editModeCoverData);
            
            // Warte kurz damit das DOM bereit ist (wichtig für Mobile)
            setTimeout(() => {
                const coverDisplay = document.getElementById('editCoverDisplay');
                console.log('[ISBN Edit] Cover Display Element gefunden:', !!coverDisplay);
                
                if (coverDisplay) {
                    // Speichere auch im Dataset (für PC)
                    coverDisplay.dataset.coverUrl = bookData.cover_image_url;
                    coverDisplay.dataset.isbnCover = 'true';
                    
                    // Zeige Loading-Spinner
                    coverDisplay.innerHTML = '<div class="cover-loading"><i class="fas fa-spinner fa-spin"></i><br>Lade Cover...</div>';
                    coverDisplay.style.display = 'block';
                    
                    // Erstelle neues Image zum Laden
                    const img = new Image();
                    const previewImg = document.createElement('img');
                    previewImg.className = 'book-cover-large';
                    previewImg.alt = 'Book Cover';
                    
                    img.onload = function() {
                        coverDisplay.innerHTML = '';
                        previewImg.src = bookData.cover_image_url;
                        coverDisplay.appendChild(previewImg);
                        console.log('[ISBN Edit] Cover erfolgreich geladen');
                        hasCover = true;
                        // Entferne Fehlermeldung falls vorhanden
                        const errorDiv = document.getElementById('editCoverErrorMessage');
                        if (errorDiv) errorDiv.innerHTML = '';
                    };
                    img.onerror = function() {
                        console.error('[ISBN Edit] Cover konnte nicht geladen werden:', bookData.cover_image_url);
                        // Zeige Fehlermeldung unter dem Cover-Bereich
                        const errorDiv = document.getElementById('editCoverErrorMessage');
                        if (errorDiv) {
                            errorDiv.innerHTML = '<div style="color: #ef4444; font-size: 14px;"><i class="fas fa-exclamation-triangle"></i> Cover konnte nicht geladen werden</div>';
                        }
                    };
                    img.src = bookData.cover_image_url;
                } else {
                    console.error('[ISBN Edit] Cover Display Element nicht gefunden!');
                }
            }, 100);
        } else {
            // Kein Cover vorhanden - zeige Meldung
            setTimeout(() => {
                const errorDiv = document.getElementById('editCoverErrorMessage');
                if (errorDiv) {
                    errorDiv.innerHTML = '<div style="color: #f59e0b; font-size: 14px;"><i class="fas fa-info-circle"></i> Kein Cover verfügbar</div>';
                }
            }, 100);
        }
        
        // Entferne alte Fehlermeldung falls vorhanden
        const oldError = isbnInput.parentElement.querySelector('.isbn-error');
        if (oldError) oldError.remove();
    } catch (error) {
        console.error('ISBN Suche Fehler:', error);
        
        // Zeige Fehler unter dem ISBN-Feld
        let errorDiv = isbnInput.parentElement.querySelector('.isbn-error');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'isbn-error';
            errorDiv.style.cssText = 'color: #ef4444; font-size: 14px; margin-top: 8px;';
            isbnInput.parentElement.appendChild(errorDiv);
        }
        errorDiv.textContent = '❌ Die eingegebene ISBN konnte nicht gefunden werden. Bitte überprüfen Sie die ISBN oder geben Sie die Daten manuell ein.';
        
        showMessage(document.getElementById('editBookSection'), '❌ ISBN nicht gefunden', 'error');
    } finally {
        if (searchBtn) {
            searchBtn.disabled = false;
            searchBtn.innerHTML = originalBtnText;
        }
        isbnInput.disabled = false;
    }
}

// Barcode Scanner Funktionen
let currentScannerContext = null; // 'book', 'wishlist', or 'edit'

// Check if scanner is available and hide button if not
function checkScannerAvailability() {
    const isSecureContext = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    const hasMediaDevices = navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
    
    return isSecureContext && hasMediaDevices;
}

function startBarcodeScanner() {
    if (!checkScannerAvailability()) {
        showMessage(null, 'Barcode-Scanner benötigt HTTPS. Bitte ISBN manuell eingeben.', 'warning');
        return;
    }
    currentScannerContext = 'book';
    initScanner();
}

function startBarcodeScannerWishlist() {
    if (!checkScannerAvailability()) {
        showMessage(null, 'Barcode-Scanner benötigt HTTPS. Bitte ISBN manuell eingeben.', 'warning');
        return;
    }
    currentScannerContext = 'wishlist';
    initScanner();
}

function startBarcodeScannerEdit(bookId) {
    if (!checkScannerAvailability()) {
        showMessage(null, 'Barcode-Scanner benötigt HTTPS. Bitte ISBN manuell eingeben.', 'warning');
        return;
    }
    currentScannerContext = 'edit';
    currentScannerContext.bookId = bookId;
    initScanner();
}

function initScanner() {
    // Check if running on HTTPS or localhost
    const isSecureContext = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    
    if (!isSecureContext) {
        showMessage(null, 'Barcode-Scanner benötigt HTTPS oder localhost. Bitte ISBN manuell eingeben oder HTTPS verwenden.', 'error');
        console.warn('Barcode-Scanner erfordert HTTPS. Aktuelles Protokoll:', window.location.protocol);
        return;
    }
    
    const scannerModal = document.getElementById('barcodeScannerModal');
    scannerModal.classList.add('active');
    
    // Check if Quagga is available
    if (typeof Quagga === 'undefined') {
        showMessage(null, 'Barcode-Scanner konnte nicht geladen werden.', 'error');
        stopScanner();
        return;
    }
    
    // Check if getUserMedia is supported
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showMessage(null, 'Ihr Browser unterstützt keinen Kamera-Zugriff. Bitte ISBN manuell eingeben.', 'error');
        stopScanner();
        return;
    }
    
    // Initialize Quagga with correct configuration
    Quagga.init({
        inputStream: {
            name: "Live",
            type: "LiveStream",
            target: document.querySelector('#interactive'),
            constraints: {
                width: { min: 640, ideal: 1280, max: 1920 },
                height: { min: 480, ideal: 720, max: 1080 },
                facingMode: "environment", // Rückkamera auf Mobilgeräten
                aspectRatio: { min: 1, max: 2 },
                advanced: [{ torch: true }] // Versuche Taschenlampe direkt zu aktivieren
            },
            area: { // defines rectangle of the detection/localization area
                top: "0%",    // top offset
                right: "0%",  // right offset
                left: "0%",   // left offset
                bottom: "0%"  // bottom offset
            }
        },
        decoder: {
            readers: [
                "ean_reader",      // EAN-13 (häufigster Buchbarcode)
                "ean_8_reader",    // EAN-8
                "upc_reader",      // UPC
                "code_128_reader", // Code 128
                "code_39_reader"   // Code 39
            ],
            debug: {
                drawBoundingBox: true,
                showFrequency: false,
                drawScanline: true,
                showPattern: false
            }
        },
        locate: true,
        locator: {
            halfSample: true,
            patchSize: "medium"
        },
        frequency: 10
    }, function(err) {
        if (err) {
            console.error('Scanner Initialisierung fehlgeschlagen:', err);
            let errorMessage = 'Kamera-Zugriff fehlgeschlagen. ';
            
            if (err.name === 'NotAllowedError') {
                errorMessage += 'Bitte erlauben Sie den Kamera-Zugriff in Ihren Browser-Einstellungen.';
            } else if (err.name === 'NotFoundError') {
                errorMessage += 'Keine Kamera gefunden.';
            } else if (err.name === 'NotReadableError') {
                errorMessage += 'Kamera wird bereits von einer anderen Anwendung verwendet.';
            } else if (err.message && err.message.includes('getUserMedia')) {
                errorMessage += 'Barcode-Scanner funktioniert nur mit HTTPS oder auf localhost.';
            } else {
                errorMessage += err.message || 'Unbekannter Fehler.';
            }
            
            showMessage(null, errorMessage, 'error');
            stopScanner();
            return;
        }
        console.log("Scanner initialisiert");
        Quagga.start();
    });
    
    // Barcode erkannt
    Quagga.onDetected(function(result) {
        if (result && result.codeResult && result.codeResult.code) {
            const isbn = result.codeResult.code;
            console.log("Barcode erkannt:", isbn, "Länge:", isbn.length);
            
            // Validiere ISBN-Länge (ISBN-10 oder ISBN-13)
            // Entferne nicht-numerische Zeichen außer X (für ISBN-10)
            const cleanIsbn = isbn.replace(/[^0-9X]/gi, '');
            
            if (cleanIsbn.length !== 10 && cleanIsbn.length !== 13) {
                console.warn("Ungültige ISBN-Länge:", cleanIsbn.length, "- Erwartet: 10 oder 13 Zeichen. Ignoriere Scan.");
                // Zeige kurz Feedback aber scanne weiter
                const interactive = document.getElementById('interactive');
                if (interactive) {
                    const originalBorder = interactive.style.border;
                    interactive.style.border = '3px solid #ef4444';
                    setTimeout(() => {
                        interactive.style.border = originalBorder;
                    }, 300);
                }
                return; // Ignoriere diesen Scan und scanne weiter
            }
            
            console.log("Gültige ISBN erkannt:", cleanIsbn);
            
            // Stop scanner
            const savedContext = currentScannerContext;
            const savedBookId = currentScannerContext && currentScannerContext.bookId;
            stopScanner();
            
            // Fill ISBN field and trigger search
            if (savedContext === 'book') {
                document.getElementById('bookISBN').value = cleanIsbn;
                searchByISBN();
            } else if (savedContext === 'wishlist') {
                document.getElementById('wishlistISBN').value = cleanIsbn;
                searchByISBNWishlist();
            } else if (savedContext === 'edit') {
                document.getElementById('bookISBN').value = cleanIsbn;
                searchByISBNEdit(null, savedBookId);
            }
        }
    });
    
    // Close button
    document.getElementById('closeScannerBtn').onclick = stopScanner;
    document.getElementById('cancelScanBtn').onclick = stopScanner;
    
    // Torch/Flashlight toggle - check if device supports it
    const torchBtn = document.getElementById('toggleTorchBtn');
    const torchStatus = document.getElementById('torchStatusMessage');
    if (torchBtn) {
        // Wait a bit for camera to be ready
        setTimeout(() => {
            const track = Quagga.CameraAccess.getActiveTrack();
            console.log('Checking torch support - Track:', track);
            
            if (!track) {
                if (torchStatus) {
                    torchStatus.textContent = '⚠️ Kein Kamera-Track gefunden';
                    torchStatus.style.color = '#ef4444';
                }
                return;
            }
            
            const capabilities = track.getCapabilities ? track.getCapabilities() : {};
            const settings = track.getSettings ? track.getSettings() : {};
            console.log('Track capabilities:', capabilities);
            console.log('Track settings:', settings);
            
            // Prüfe ob torch in capabilities oder settings vorhanden ist
            const hasTorchCapability = capabilities.torch === true;
            const hasTorchInSettings = 'torch' in settings;
            
            if (hasTorchCapability || hasTorchInSettings) {
                // Device supports torch
                torchBtn.style.display = '';
                torchBtn.onclick = toggleTorch;
                if (torchStatus) {
                    torchStatus.textContent = settings.torch ? '💡 Taschenlampe ist AN' : '💡 Taschenlampe verfügbar - Klicken zum Einschalten';
                    torchStatus.style.color = '#10b981';
                }
                // Wenn torch bereits aktiv ist (durch constraints), setze Button-Status
                if (settings.torch) {
                    torchEnabled = true;
                    torchBtn.classList.add('active');
                    torchBtn.innerHTML = '<i class="fas fa-lightbulb"></i> Taschenlampe AN';
                }
            } else {
                if (torchStatus) {
                    torchStatus.innerHTML = '⚠️ Taschenlampe wird vom Browser nicht unterstützt<br><small>Versuche Chrome oder öffne in externem Browser</small>';
                    torchStatus.style.color = '#f59e0b';
                }
            }
        }, 1500); // Längere Wartezeit für mobile Geräte
    }
}

let torchEnabled = false;

function toggleTorch() {
    try {
        const track = Quagga.CameraAccess.getActiveTrack();
        if (!track) {
            console.warn('Kein aktiver Video-Track gefunden');
            return;
        }
        
        const capabilities = track.getCapabilities();
        if (!capabilities || !capabilities.torch) {
            console.warn('Gerät unterstützt keine Taschenlampe');
            showMessage(null, 'Ihr Gerät unterstützt keine Taschenlampe', 'error');
            return;
        }
        
        torchEnabled = !torchEnabled;
        
        track.applyConstraints({
            advanced: [{ torch: torchEnabled }]
        }).then(() => {
            console.log('Taschenlampe:', torchEnabled ? 'AN' : 'AUS');
            const torchBtn = document.getElementById('toggleTorchBtn');
            if (torchBtn) {
                if (torchEnabled) {
                    torchBtn.classList.add('active');
                    torchBtn.innerHTML = '<i class="fas fa-lightbulb"></i> Taschenlampe AN';
                } else {
                    torchBtn.classList.remove('active');
                    torchBtn.innerHTML = '<i class="fas fa-lightbulb"></i> Taschenlampe';
                }
            }
        }).catch(err => {
            console.error('Fehler beim Umschalten der Taschenlampe:', err);
            showMessage(null, 'Taschenlampe konnte nicht umgeschaltet werden', 'error');
        });
    } catch (err) {
        console.error('Fehler beim Zugriff auf Taschenlampe:', err);
    }
}

function stopScanner() {
    if (typeof Quagga !== 'undefined') {
        Quagga.stop();
    }
    const scannerModal = document.getElementById('barcodeScannerModal');
    scannerModal.classList.remove('active');
    currentScannerContext = null;
    
    // Reset torch state
    torchEnabled = false;
    const torchBtn = document.getElementById('toggleTorchBtn');
    if (torchBtn) {
        torchBtn.style.display = 'none';
        torchBtn.classList.remove('active');
        torchBtn.innerHTML = '<i class="fas fa-lightbulb"></i> Taschenlampe';
    }
    
    // Clear status message
    const torchStatus = document.getElementById('torchStatusMessage');
    if (torchStatus) {
        torchStatus.textContent = '';
    }
}

// Buch-Management-Funktionen
async function createBook() {
    // Finde den Submit-Button
    const submitBtn = document.querySelector('#bookForm button[type="submit"]');
    let originalBtnText = '';
    
    if (submitBtn) {
        originalBtnText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Wird gespeichert...';
    }
    
    try {
        const volumeValue = document.getElementById('bookVolume').value.trim();
        const isbnInput = document.getElementById('bookISBN');
        const isbnValue = isbnInput ? isbnInput.value.trim() : '';
        
        console.log('=== CREATE BOOK DEBUG ===');
        console.log('[createBook] ISBN Input Element:', isbnInput);
        console.log('[createBook] ISBN Input .value:', isbnInput ? isbnInput.value : 'INPUT NOT FOUND');
        console.log('[createBook] ISBN nach trim:', isbnValue);
        
        const bookData = {
            title: document.getElementById('bookTitle').value,
            author: document.getElementById('bookAuthor').value,
            isbn: isbnValue,
            genre: document.getElementById('bookGenre').value,
            pages: parseInt(document.getElementById('bookPages').value),
            format: document.getElementById('bookFormat').value,
            publisher: document.getElementById('bookPublisher').value,
            publish_date: document.getElementById('bookPublishDate').value,
            series: document.getElementById('bookSeries').value,
            volume: volumeValue ? parseInt(volumeValue) : 0,
            status: document.getElementById('bookStatus').value
        };
        
        console.log('[createBook] Zu speichernde Daten:', bookData);
        console.log('[createBook] bookData.isbn:', bookData.isbn);
        console.log('=== CREATE BOOK DEBUG END ===');
        
        const response = await apiCall('/books', {
            method: 'POST',
            body: bookData
        });
        
        // Check if cover from ISBN should be downloaded
        const previewDiv = document.getElementById('newBookCoverPreview');
        const hasIsbnCover = previewDiv && previewDiv.dataset.isbnCover === 'true' && previewDiv.dataset.coverUrl;
        
        if (hasIsbnCover) {
            // Download cover from URL now
            try {
                const isbnInput = document.getElementById('bookISBN');
                const isbn = isbnInput ? isbnInput.value.trim() : '';
                
                const coverResult = await apiCall('/download-cover', {
                    method: 'POST',
                    body: {
                        cover_url: previewDiv.dataset.coverUrl,
                        isbn: isbn
                    }
                });
                
                if (coverResult.cover_path) {
                    // Update book with downloaded cover
                    await apiCall(`/books/${response.id}`, {
                        method: 'PUT',
                        body: {
                            ...bookData,
                            cover_image: coverResult.cover_path
                        }
                    });
                }
            } catch (coverError) {
                console.error('Fehler beim Herunterladen des Covers:', coverError);
                // Continue anyway, book is saved
            }
        } else {
            // Cover upload if file selected
            const coverFile = document.getElementById('newBookCover');
            if (coverFile && coverFile.files.length > 0) {
                const formData = new FormData();
                formData.append('cover', coverFile.files[0]);
                
                await fetch(`/api/books/${response.id}/cover`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    },
                    body: formData
                });
            }
        }
        
        closeModal();
        loadBooks();
        showMessage(null, 'Buch erfolgreich hinzugefügt!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
    } finally {
        // Button wieder aktivieren
        if (submitBtn && originalBtnText) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
        }
    }
}

async function deleteBook(bookId) {
    if (!confirm('Sind Sie sicher, dass Sie dieses Buch löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/books/${bookId}`, {
            method: 'DELETE'
        });
        
        
        closeModal();
        loadBooks();
        showMessage(null, 'Buch erfolgreich gelöscht!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Löschen: ' + error.message, 'error');
    }
}

async function saveBasicInfo(bookId) {
    try {
        const volumeValue = document.getElementById('bookVolume').value.trim();
        const isbnInput = document.getElementById('bookISBN');
        const isbnValue = isbnInput ? isbnInput.value.trim() : '';
        
        console.log('=== SAVE BASIC INFO DEBUG ===');
        console.log('[saveBasicInfo] ISBN Input Element:', isbnInput);
        console.log('[saveBasicInfo] ISBN Input .value:', isbnInput ? isbnInput.value : 'INPUT NOT FOUND');
        console.log('[saveBasicInfo] ISBN nach trim:', isbnValue);
        console.log('[saveBasicInfo] ISBN Länge:', isbnValue.length);
        
        const bookData = {
            title: document.getElementById('bookTitle').value,
            author: document.getElementById('bookAuthor').value,
            isbn: isbnValue,
            genre: document.getElementById('bookGenre').value,
            pages: parseInt(document.getElementById('bookPages').value),
            format: document.getElementById('bookFormat').value,
            publisher: document.getElementById('bookPublisher').value,
            publish_date: document.getElementById('bookPublishDate').value,
            series: document.getElementById('bookSeries').value,
            volume: volumeValue ? parseInt(volumeValue) : 0,
            status: document.getElementById('bookStatus').value
        };
        
        console.log('[saveBasicInfo] Zu speichernde Daten:', bookData);
        console.log('[saveBasicInfo] bookData.isbn:', bookData.isbn);
        console.log('=== SAVE BASIC INFO DEBUG END ===');
        
        await apiCall(`/books/${bookId}`, {
            method: 'PUT',
            body: bookData
        });
        
        // Check if cover from ISBN should be downloaded
        // Verwende globale Variable als Fallback (wichtig für Mobile!)
        console.log('[Save] Globale Cover-Daten:', editModeCoverData);
        
        const coverDisplay = document.getElementById('editCoverDisplay');
        console.log('[Save] Cover Display gefunden:', !!coverDisplay);
        
        // Prüfe zuerst globale Variable (funktioniert immer), dann Dataset
        const hasIsbnCover = editModeCoverData || 
            (coverDisplay && coverDisplay.dataset.isbnCover === 'true' && coverDisplay.dataset.coverUrl);
        
        console.log('[Save] hasIsbnCover:', hasIsbnCover);
        
        if (hasIsbnCover) {
            console.log('[Save] Cover wird heruntergeladen...');
            // Download cover from URL now
            try {
                const coverUrl = editModeCoverData ? editModeCoverData.coverUrl : coverDisplay.dataset.coverUrl;
                console.log('[Save] Cover URL:', coverUrl);
                
                const coverResult = await apiCall('/download-cover', {
                    method: 'POST',
                    body: {
                        cover_url: coverUrl,
                        isbn: isbnValue
                    }
                });
                
                if (coverResult.cover_path) {
                    console.log('[Save] Cover erfolgreich heruntergeladen:', coverResult.cover_path);
                    // Update book with downloaded cover
                    await apiCall(`/books/${bookId}`, {
                        method: 'PUT',
                        body: {
                            ...bookData,
                            cover_image: coverResult.cover_path
                        }
                    });
                    
                    // Lösche globale Cover-Daten nach erfolgreichem Upload
                    editModeCoverData = null;
                }
            } catch (coverError) {
                console.error('[Save] Fehler beim Herunterladen des Covers:', coverError);
                // Continue anyway, book data is saved
            }
        } else {
            // Cover upload if file selected (like in createBook)
            const editCoverInput = document.getElementById('editBookCover');
            if (editCoverInput && editCoverInput.files && editCoverInput.files.length > 0) {
                try {
                    const formData = new FormData();
                    formData.append('cover', editCoverInput.files[0]);
                    
                    const uploadResponse = await fetch(`${currentServerUrl}/api/books/${bookId}/cover`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${currentToken}`
                        },
                        body: formData
                    });
                    
                    if (!uploadResponse.ok) {
                        throw new Error('Upload fehlgeschlagen');
                    }
                } catch (uploadError) {
                    console.error('Cover-Upload Fehler:', uploadError);
                    showMessage(null, 'Cover-Upload fehlgeschlagen', 'error');
                }
            }
        }
        
        // Reload book details
        showBookDetails(bookId);
        showMessage(null, 'Grundinformationen erfolgreich gespeichert!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Speichern: ' + error.message, 'error');
    }
}

async function saveRatings(bookId) {
    try {
        const ratingData = {
            rating: parseInt(document.querySelector('[data-rating="rating"]').dataset.value) || 0,
            spice: parseInt(document.querySelector('[data-rating="spice"]').dataset.value) || 0,
            tension: parseInt(document.getElementById('bookTension').value) || 0,
            fiction: document.getElementById('bookFiction').value === 'Fiction'
        };
        
        await apiCall(`/books/${bookId}`, {
            method: 'PUT',
            body: ratingData
        });
        
        // Reload book details
        showBookDetails(bookId);
        showMessage(null, 'Bewertungen erfolgreich gespeichert!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Speichern: ' + error.message, 'error');
    }
}

async function saveReview(bookId) {
    try {
        const reviewData = {
            review: document.getElementById('bookReview').value
        };
        
        await apiCall(`/books/${bookId}`, {
            method: 'PUT',
            body: reviewData
        });
        
        // Reload book details
        showBookDetails(bookId);
        showMessage(null, 'Rezension erfolgreich gespeichert!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Speichern: ' + error.message, 'error');
    }
}

// Cover Upload Funktionen
function showCoverUpload(bookId) {
    const form = document.getElementById('coverUploadForm');
    if (form) {
        form.style.display = 'block';
    }
}

function cancelCoverUpload() {
    const form = document.getElementById('coverUploadForm');
    if (form) {
        form.style.display = 'none';
    }
}

function previewCover(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('coverPreview');
            const previewImage = document.getElementById('previewImage');
            
            if (preview && previewImage) {
                previewImage.src = e.target.result;
                preview.style.display = 'block';
                document.getElementById('uploadCoverBtn').disabled = false;
            }
        };
        reader.readAsDataURL(input.files[0]);
    }
}

function previewNewBookCover(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('newBookCoverPreview');
            const previewImage = document.getElementById('newBookPreviewImage');
            
            if (preview && previewImage) {
                previewImage.src = e.target.result;
                preview.style.display = 'block';
            }
        };
        reader.readAsDataURL(input.files[0]);
    }
}

function previewEditBookCover(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        
        // Validiere Dateityp
        if (!file.type.startsWith('image/')) {
            showMessage(null, 'Bitte wählen Sie eine Bilddatei aus', 'error');
            input.value = '';
            return;
        }
        
        const reader = new FileReader();
        reader.onload = function(e) {
            const editCoverDisplay = document.getElementById('editCoverDisplay');
            if (editCoverDisplay) {
                editCoverDisplay.innerHTML = `<img src="${e.target.result}" alt="Book Cover" class="book-cover-large">`;
            }
        };
        reader.readAsDataURL(file);
    }
}

async function uploadCover(bookId) {
    const fileInput = document.getElementById('coverFile');
    if (!fileInput.files.length) {
        showMessage(null, 'Bitte wählen Sie eine Datei aus.', 'error');
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('cover', fileInput.files[0]);
        
        const response = await fetch(`/api/books/${bookId}/cover`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${currentToken}`
            },
            body: formData
        });
        
        if (response.ok) {
            showMessage(null, 'Cover erfolgreich hochgeladen!', 'success');
            showBookDetails(bookId); // Reload to show new cover
        } else {
            throw new Error('Cover-Upload fehlgeschlagen');
        }
    } catch (error) {
        showMessage(null, 'Fehler beim Hochladen: ' + error.message, 'error');
    }
}

// Wishlist Funktionen
async function loadWishlist(search = '') {
    try {
        const wishlist = await apiCall(`/wishlist${search ? `?search=${encodeURIComponent(search)}` : ''}`);
        const wishlistEl = document.getElementById('wishlistList');
        
        if (!wishlistEl) {
            console.error('Wishlist element not found');
            return;
        }
        
        wishlistEl.innerHTML = '';
        
        if (wishlist.length > 0) {
            wishlist.forEach(item => {
                const wishlistItem = createWishlistItem(item);
                wishlistEl.appendChild(wishlistItem);
            });
        } else {
            wishlistEl.innerHTML = '<div class="wishlist-item"><p>Keine Wunschliste-Einträge gefunden.</p></div>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Wunschliste:', error);
    }
}

function searchWishlist() {
    const search = document.getElementById('wishlistSearch').value;
    loadWishlist(search);
}

function createWishlistItem(item) {
    const element = document.createElement('div');
    element.className = 'wishlist-item';
    
    const coverImageUrl = item.cover_image 
        ? `/uploads/covers/${item.cover_image}` 
        : (item.coverImage ? `/uploads/covers/${item.coverImage}` : null);
    
    element.innerHTML = `
        <div class="wishlist-cover">
            ${coverImageUrl ? `<img src="${coverImageUrl}" alt="Cover">` : '<i class="fas fa-book"></i>'}
        </div>
        <div class="wishlist-info">
            <div class="wishlist-title">${escapeHtml(item.title)}</div>
            <div class="wishlist-meta">von ${escapeHtml(item.author)}</div>
            <div class="wishlist-meta">${escapeHtml(item.publisher)} • ${formatDate(item.publish_date || item.publishDate)}</div>
        </div>
        <div class="wishlist-actions">
            <button class="btn btn-primary" onclick="showWishlistDetails(${item.id})">
                <i class="fas fa-eye"></i> Details
            </button>
            <button class="btn btn-success" onclick="buyWishlistItem(${item.id})">
                <i class="fas fa-shopping-cart"></i> Gekauft
            </button>
            <button class="btn btn-danger" onclick="deleteWishlistItem(${item.id})">
                <i class="fas fa-trash"></i> Löschen
            </button>
        </div>
    `;
    
    return element;
}

function showAddWishlistModal() {
    const modalBody = `
        <form id="wishlistForm">
            <!-- ISBN Suche -->
            <div class="form-group">
                <label for="wishlistISBN">ISBN (optional)</label>
                <div class="isbn-buttons-group">
                    <button type="button" class="btn btn-primary" onclick="searchByISBNWishlist(event)">
                        <i class="fas fa-search"></i> Suchen
                    </button>
                    <button type="button" class="btn btn-secondary" id="scanBarcodeBtn" onclick="startBarcodeScannerWishlist()">
                        <i class="fas fa-barcode"></i> Scannen
                    </button>
                </div>
                <input type="text" id="wishlistISBN" placeholder="ISBN eingeben...">
                <small>Buchdaten werden automatisch ausgefüllt</small>
            </div>

            <!-- Cover Upload für Wunschliste -->
            <div class="form-group">
                <label for="newWishlistCover">Cover hochladen</label>
                <input type="file" id="newWishlistCover" accept="image/*" onchange="previewNewWishlistCover(this)">
                <small>Unterstützte Formate: JPG, PNG, WebP</small>
                <div id="wishlistCoverErrorMessage" style="margin-top: 8px;"></div>
                <div id="newWishlistCoverPreview" class="cover-preview" style="display: none;">
                    <img id="newWishlistPreviewImage" alt="Vorschau">
                </div>
            </div>
            
            <div class="form-grid">
                <div class="form-group">
                    <label for="wishlistTitle">Titel *</label>
                    <input type="text" id="wishlistTitle" required>
                </div>
                <div class="form-group">
                    <label for="wishlistAuthor">Autor *</label>
                    <input type="text" id="wishlistAuthor" required>
                </div>
                <div class="form-group">
                    <label for="wishlistGenre">Genre</label>
                    <div class="autocomplete-container">
                        <input type="text" id="wishlistGenre" placeholder="Genre eingeben...">
                        <div id="wishlistGenreSuggestions" class="autocomplete-suggestions"></div>
                    </div>
                </div>
                <div class="form-group">
                    <label for="wishlistPages">Seiten</label>
                    <input type="number" id="wishlistPages" min="1">
                </div>
                <div class="form-group">
                    <label for="wishlistPublisher">Verlag</label>
                    <div class="autocomplete-container">
                        <input type="text" id="wishlistPublisher" placeholder="Verlag eingeben...">
                        <div id="wishlistPublisherSuggestions" class="autocomplete-suggestions"></div>
                    </div>
                </div>
                <div class="form-group">
                    <label for="wishlistPublishDate">Erscheinungsdatum</label>
                    <input type="date" id="wishlistPublishDate">
                </div>
                <div class="form-group">
                    <label for="wishlistSeries">Reihe</label>
                    <input type="text" id="wishlistSeries">
                </div>
                <div class="form-group">
                    <label for="wishlistVolume">Band</label>
                    <input type="text" id="wishlistVolume">
                </div>
            </div>
            
            <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                <button type="submit" class="btn btn-primary">Hinzufügen</button>
            </div>
        </form>
    `;
    
    showModal('Zur Wunschliste hinzufügen', modalBody);
    
    // Load genres and publishers
    setupGenreAutocomplete('wishlistGenre');
    setupPublisherAutocomplete('wishlistPublisher');
    
    document.getElementById('wishlistForm').onsubmit = async (e) => {
        e.preventDefault();
        
        try {
            const volumeValue = document.getElementById('wishlistVolume').value.trim();
            const wishlistData = {
                title: document.getElementById('wishlistTitle').value.trim(),
                author: document.getElementById('wishlistAuthor').value.trim(),
                genre: document.getElementById('wishlistGenre').value,
                pages: parseInt(document.getElementById('wishlistPages').value) || 0,
                publisher: document.getElementById('wishlistPublisher').value,
                publish_date: document.getElementById('wishlistPublishDate').value,
                series: document.getElementById('wishlistSeries').value.trim(),
                volume: volumeValue ? parseInt(volumeValue) : 0
            };
            
            if (!wishlistData.title || !wishlistData.author) {
                alert('Bitte füllen Sie alle Pflichtfelder aus.');
                return;
            }
            
            const response = await apiCall('/wishlist', {
                method: 'POST',
                body: wishlistData
            });
            
            // Check if cover from ISBN should be downloaded
            const previewDiv = document.getElementById('newWishlistCoverPreview');
            const hasIsbnCover = previewDiv && previewDiv.dataset.isbnCover === 'true' && previewDiv.dataset.coverUrl;
            
            if (hasIsbnCover) {
                // Download cover from URL now
                try {
                    const isbnInput = document.getElementById('wishlistISBN');
                    const isbn = isbnInput ? isbnInput.value.trim() : '';
                    
                    const coverResult = await apiCall('/download-cover', {
                        method: 'POST',
                        body: {
                            cover_url: previewDiv.dataset.coverUrl,
                            isbn: isbn
                        }
                    });
                    
                    if (coverResult.cover_path) {
                        // Update wishlist item with downloaded cover
                        await apiCall(`/wishlist/${response.id}`, {
                            method: 'PUT',
                            body: {
                                ...wishlistData,
                                cover_image: coverResult.cover_path
                            }
                        });
                    }
                } catch (coverError) {
                    console.error('Fehler beim Herunterladen des Covers:', coverError);
                    // Continue anyway, wishlist item is saved
                }
            } else {
                // Cover upload if file selected
                const coverFile = document.getElementById('newWishlistCover');
                if (coverFile && coverFile.files.length > 0) {
                    const formData = new FormData();
                    formData.append('cover', coverFile.files[0]);
                    
                    await fetch(`/api/wishlist/${response.id}/cover`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${currentToken}`
                        },
                        body: formData
                    });
                }
            }
            
            closeModal();
            loadWishlist();
            showMessage(null, 'Zur Wunschliste hinzugefügt!', 'success');
        } catch (error) {
            console.error('Error adding wishlist item:', error);
            alert('Fehler beim Hinzufügen: ' + error.message);
        }
    };
}

async function showWishlistDetails(wishlistId) {
    try {
        const item = await apiCall(`/wishlist/${wishlistId}`);
        
        const coverImageUrl = item.cover_image 
            ? `/uploads/covers/${item.cover_image}` 
            : (item.coverImage ? `/uploads/covers/${item.coverImage}` : null);
        
        const modalBody = `
            <form id="editWishlistForm">
                <input type="hidden" id="wishlistId" value="${item.id}">
                
                <!-- Cover Upload für Wunschliste -->
                <div class="form-group">
                    <label for="editWishlistCover">Cover hochladen (optional)</label>
                    <input type="file" id="editWishlistCover" accept="image/*" onchange="previewEditWishlistCover(this)">
                    <small>Unterstützte Formate: JPG, PNG, WebP</small>
                    <div id="editWishlistCoverPreview" class="cover-preview" ${coverImageUrl ? '' : 'style="display: none;"'}>
                        <img id="editWishlistPreviewImage" src="${coverImageUrl || ''}" alt="Vorschau">
                    </div>
                </div>
                
                <div class="form-grid">
                    <div class="form-group">
                        <label for="editWishlistTitle">Titel *</label>
                        <input type="text" id="editWishlistTitle" value="${escapeHtml(item.title)}" required>
                    </div>
                    <div class="form-group">
                        <label for="editWishlistAuthor">Autor *</label>
                        <input type="text" id="editWishlistAuthor" value="${escapeHtml(item.author)}" required>
                    </div>
                    <div class="form-group">
                        <label for="editWishlistGenre">Genre</label>
                        <div class="autocomplete-container">
                            <input type="text" id="editWishlistGenre" placeholder="Genre eingeben...">
                            <div id="editWishlistGenreSuggestions" class="autocomplete-suggestions"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="editWishlistPages">Seiten</label>
                        <input type="number" id="editWishlistPages" value="${item.pages || ''}" min="1">
                    </div>
                    <div class="form-group">
                        <label for="editWishlistPublisher">Verlag</label>
                        <div class="autocomplete-container">
                            <input type="text" id="editWishlistPublisher" value="${escapeHtml(item.publisher || '')}" placeholder="Verlag eingeben...">
                            <div id="editWishlistPublisherSuggestions" class="autocomplete-suggestions"></div>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="editWishlistPublishDate">Erscheinungsdatum</label>
                        <input type="date" id="editWishlistPublishDate" value="${item.publish_date ? item.publish_date.split('T')[0] : (item.publishDate ? item.publishDate.split('T')[0] : '')}">
                    </div>
                    <div class="form-group">
                        <label for="editWishlistSeries">Reihe</label>
                        <input type="text" id="editWishlistSeries" value="${escapeHtml(item.series || '')}">
                    </div>
                    <div class="form-group">
                        <label for="editWishlistVolume">Band</label>
                        <input type="text" id="editWishlistVolume" value="${item.volume || ''}">
                    </div>
                </div>
                
                <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                    <button type="submit" class="btn btn-primary">Speichern</button>
                </div>
            </form>
        `;
        
        showModal('Wunschliste-Eintrag bearbeiten', modalBody);
        
        // Load genres and setup publisher autocomplete
        setupGenreAutocomplete('editWishlistGenre', item.genre);
        setupPublisherAutocomplete('editWishlistPublisher', item.publisher);
        
        document.getElementById('editWishlistForm').onsubmit = async (e) => {
            e.preventDefault();
            await updateWishlistItem(item.id);
        };
        
    } catch (error) {
        console.error('Fehler beim Laden der Wunschliste-Details:', error);
        showMessage(null, 'Fehler beim Laden der Details: ' + error.message, 'error');
    }
}

async function updateWishlistItem(wishlistId) {
    try {
        const volumeValue = document.getElementById('editWishlistVolume').value.trim();
        const wishlistData = {
            title: document.getElementById('editWishlistTitle').value.trim(),
            author: document.getElementById('editWishlistAuthor').value.trim(),
            genre: document.getElementById('editWishlistGenre').value,
            pages: parseInt(document.getElementById('editWishlistPages').value) || 0,
            publisher: document.getElementById('editWishlistPublisher').value.trim(),
            publish_date: document.getElementById('editWishlistPublishDate').value,
            series: document.getElementById('editWishlistSeries').value.trim(),
            volume: volumeValue ? parseInt(volumeValue) : 0,
        };
        
        // Cover Upload verarbeiten
        const coverFile = document.getElementById('editWishlistCover').files[0];
        if (coverFile) {
            const coverFormData = new FormData();
            coverFormData.append('cover', coverFile);
            
            try {
                const response = await fetch(`/api/wishlist/${wishlistId}/cover`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    },
                    body: coverFormData
                });
                
                if (!response.ok) {
                    throw new Error('Cover-Upload fehlgeschlagen');
                }
            } catch (coverError) {
                console.error('Cover-Upload Fehler:', coverError);
                showMessage(null, 'Warnung: Cover konnte nicht hochgeladen werden: ' + coverError.message, 'warning');
            }
        }
        
        // Wunschliste-Item aktualisieren
        await apiCall(`/wishlist/${wishlistId}`, {
            method: 'PUT',
            body: wishlistData
        });
        
        showMessage(null, 'Wunschliste-Eintrag erfolgreich aktualisiert!', 'success');
        closeModal();
        loadWishlist();
        
    } catch (error) {
        console.error('Fehler beim Aktualisieren:', error);
        showMessage(null, 'Fehler beim Aktualisieren: ' + error.message, 'error');
    }
}

function previewEditWishlistCover(input) {
    const file = input.files[0];
    const preview = document.getElementById('editWishlistCoverPreview');
    const img = document.getElementById('editWishlistPreviewImage');
    
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            img.src = e.target.result;
            preview.style.display = 'block';
        };
        reader.readAsDataURL(file);
    } else {
        preview.style.display = 'none';
    }
}

// Zitate-Funktionen
async function loadQuotes() {
    try {
        console.log('Loading quotes...');
        const quotes = await apiCall('/quotes');
        console.log('Quotes loaded:', quotes);
        
        const quotesContainer = document.getElementById('quotesList');
        
        if (!quotesContainer) {
            console.error('Quotes container element not found');
            return;
        }
        
        if (quotes.length === 0) {
            quotesContainer.innerHTML = '<p>Noch keine Zitate vorhanden.</p>';
            return;
        }
        
        console.log('Rendering quotes...');
        quotesContainer.innerHTML = quotes.map(quote => {
            console.log('Processing quote:', quote);
            return `
            <div class="quote-card">
                <div class="quote-content">
                    <blockquote>${escapeHtml(quote.quote)}</blockquote>
                    <div class="quote-meta">
                        <p><strong>Aus:</strong> ${escapeHtml(quote.book)}</p>
                        ${quote.page ? `<p><strong>Seite:</strong> ${quote.page}</p>` : ''}
                    </div>
                </div>
                <div class="quote-actions">
                    <button class="btn btn-danger btn-sm" onclick="deleteQuote(${quote.id})">
                        <i class="fas fa-trash"></i> Löschen
                    </button>
                </div>
            </div>
        `;
        }).join('');
        
        console.log('Quotes rendered successfully');
        
    } catch (error) {
        console.error('Fehler beim Laden der Zitate:', error);
        const quotesContainer = document.getElementById('quotesList');
        if (quotesContainer) {
            quotesContainer.innerHTML = '<p>Fehler beim Laden der Zitate.</p>';
        }
        showMessage(null, 'Fehler beim Laden der Zitate: ' + error.message, 'error');
    }
}

async function searchQuotes() {
    const searchTerm = document.getElementById('quotesSearch').value.toLowerCase();
    
    try {
        const quotes = await apiCall('/quotes');
        const filteredQuotes = quotes.filter(quote => 
            quote.quote.toLowerCase().includes(searchTerm) ||
            quote.book.toLowerCase().includes(searchTerm)
        );
        
        const quotesContainer = document.getElementById('quotesList');
        
        if (!quotesContainer) {
            console.error('Quotes container element not found');
            return;
        }
        
        if (filteredQuotes.length === 0) {
            quotesContainer.innerHTML = '<p>Keine Zitate gefunden.</p>';
            return;
        }
        
        quotesContainer.innerHTML = filteredQuotes.map(quote => `
            <div class="quote-card">
                <div class="quote-content">
                    <blockquote>${escapeHtml(quote.quote)}</blockquote>
                    <div class="quote-meta">
                        <p><strong>Aus:</strong> ${escapeHtml(quote.book)}</p>
                        ${quote.page ? `<p><strong>Seite:</strong> ${quote.page}</p>` : ''}
                    </div>
                </div>
                <div class="quote-actions">
                    <button class="btn btn-danger btn-sm" onclick="deleteQuote(${quote.id})">
                        <i class="fas fa-trash"></i> Löschen
                    </button>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Fehler beim Suchen der Zitate:', error);
        showMessage(null, 'Fehler beim Suchen der Zitate: ' + error.message, 'error');
    }
}

function showAddQuoteModal() {
    const modalBody = `
        <form id="addQuoteForm">
            <div class="form-group">
                <label for="quoteText">Zitat *</label>
                <textarea id="quoteText" rows="4" required placeholder="Das Zitat eingeben..."></textarea>
            </div>
            <div class="form-group">
                <label for="quoteBookTitle">Buchtitel *</label>
                <input type="text" id="quoteBookTitle" required placeholder="Titel des Buchs">
            </div>
            <div class="form-group">
                <label for="quotePage">Seite (optional)</label>
                <input type="number" id="quotePage" min="1" placeholder="Seitenzahl">
            </div>
            <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                <button type="submit" class="btn btn-primary">Zitat hinzufügen</button>
            </div>
        </form>
    `;
    
    showModal('Neues Zitat hinzufügen', modalBody);
    
    document.getElementById('addQuoteForm').onsubmit = async (e) => {
        e.preventDefault();
        await addQuote();
    };
}

async function addQuote() {
    try {
        const quoteData = {
            quote: document.getElementById('quoteText').value.trim(),
            book: document.getElementById('quoteBookTitle').value.trim(),
            page: parseInt(document.getElementById('quotePage').value) || 0
        };
        
        if (!quoteData.quote || !quoteData.book) {
            showMessage(null, 'Bitte füllen Sie alle Pflichtfelder aus.', 'error');
            return;
        }
        
        await apiCall('/quotes', {
            method: 'POST',
            body: quoteData
        });
        
        showMessage(null, 'Zitat erfolgreich hinzugefügt!', 'success');
        closeModal();
        loadQuotes();
        
    } catch (error) {
        console.error('Fehler beim Hinzufügen des Zitats:', error);
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
    }
}

async function deleteQuote(quoteId) {
    if (!confirm('Sind Sie sicher, dass Sie dieses Zitat löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/quotes/${quoteId}`, {
            method: 'DELETE'
        });
        
        showMessage(null, 'Zitat erfolgreich gelöscht!', 'success');
        loadQuotes();
        
    } catch (error) {
        console.error('Fehler beim Löschen des Zitats:', error);
        showMessage(null, 'Fehler beim Löschen: ' + error.message, 'error');
    }
}

// ===== WEBSOCKET FUNCTIONS =====
let wsUseSecure = null; // null = noch nicht versucht, true = wss, false = ws

function connectWebSocket() {
    if (!currentServerUrl) {
        console.warn('[WebSocket] Kein Server-URL gesetzt, warte...');
        return;
    }

    // Wenn bereits verbunden, nichts tun
    if (ws && ws.readyState === WebSocket.OPEN) {
        return;
    }

    try {
        // Wähle Protokoll: wenn wsUseSecure noch nicht gesetzt, versuche HTTPS-entsprechendes Protokoll
        // Wenn bereits fehlgeschlagen, verwende das andere Protokoll
        let wsProtocol;
        if (wsUseSecure === null) {
            // Erster Versuch: verwende Protokoll entsprechend der aktuellen Seite
            wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        } else if (wsUseSecure === true) {
            wsProtocol = 'wss';
        } else {
            wsProtocol = 'ws';
        }
        
        const wsUrl = currentServerUrl.replace(/^http(s)?:\/\//, `${wsProtocol}://`) + '/ws';
        
        console.log('[WebSocket] Verbinde zu:', wsUrl);
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('[WebSocket] Verbindung hergestellt mit Protokoll:', wsProtocol);
            wsReconnectAttempts = 0;
            // Merke erfolgreiches Protokoll
            wsUseSecure = (wsProtocol === 'wss');
            
            // Clear reconnect timer
            if (wsReconnectTimer) {
                clearTimeout(wsReconnectTimer);
                wsReconnectTimer = null;
            }
        };

        ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                handleWebSocketMessage(message);
            } catch (error) {
                console.error('[WebSocket] Fehler beim Parsen der Nachricht:', error);
            }
        };

        ws.onerror = (error) => {
            console.error('[WebSocket] Fehler:', error);
            
            // Bei erstem Fehler mit wss, prüfe ob Mixed Content Problem
            if (wsUseSecure === null && wsProtocol === 'wss') {
                if (window.location.protocol === 'https:') {
                    console.warn('[WebSocket] HTTPS-Seite kann keine unsicheren WebSocket-Verbindungen herstellen.');
                    console.warn('[WebSocket] Konfiguriere Nginx für WebSocket-Proxy oder verwende WSS.');
                    // Versuche nicht WS, da es blockiert wird
                    wsReconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS; // Stoppe Reconnect-Versuche
                } else {
                    console.log('[WebSocket] WSS fehlgeschlagen, versuche WS...');
                    wsUseSecure = false; // Nächster Versuch mit ws
                }
            }
        };

        ws.onclose = () => {
            console.log('[WebSocket] Verbindung geschlossen');
            ws = null;
            
            // Reconnect versuchen
            if (wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
                wsReconnectAttempts++;
                const delay = wsReconnectAttempts === 1 && wsUseSecure === false ? 100 : WS_RECONNECT_DELAY;
                console.log(`[WebSocket] Reconnect-Versuch ${wsReconnectAttempts}/${WS_MAX_RECONNECT_ATTEMPTS} in ${delay}ms`);
                wsReconnectTimer = setTimeout(() => {
                    connectWebSocket();
                }, delay);
            } else {
                console.warn('[WebSocket] Maximale Reconnect-Versuche erreicht');
            }
        };
    } catch (error) {
        console.error('[WebSocket] Verbindungsfehler:', error);
        
        // Bei SecurityError (Mixed Content) keine weiteren Versuche
        if (error.name === 'SecurityError') {
            console.warn('[WebSocket] Live-Updates deaktiviert: HTTPS-Seite benötigt WSS oder Nginx-Proxy');
            wsReconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS;
        }
    }
}

function disconnectWebSocket() {
    if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
    }
    
    if (ws) {
        ws.close();
        ws = null;
    }
    
    wsReconnectAttempts = 0;
    wsUseSecure = null; // Reset für nächste Verbindung
}

function handleWebSocketMessage(message) {
    console.log('[WebSocket] Empfangene Nachricht:', message);

    switch (message.type) {
        case 'book_created':
        case 'book_updated':
        case 'book_deleted':
            if (currentPage === 'books' || currentPage === 'dashboard') {
                console.log('[WebSocket] Lade Bücher neu...');
                loadBooks('', true); // preserveScroll=true bei WebSocket-Updates
                if (currentPage === 'dashboard') {
                    loadDashboard();
                }
            }
            break;

        case 'wishlist_created':
        case 'wishlist_updated':
        case 'wishlist_deleted':
            if (currentPage === 'wishlist') {
                console.log('[WebSocket] Lade Wunschliste neu...');
                loadWishlist();
            }
            if (currentPage === 'dashboard') {
                loadDashboard();
            }
            break;

        case 'quote_created':
        case 'quote_deleted':
            if (currentPage === 'quotes') {
                console.log('[WebSocket] Lade Zitate neu...');
                loadQuotes();
            }
            if (currentPage === 'dashboard') {
                loadDashboard();
            }
            break;

        default:
            console.warn('[WebSocket] Unbekannter Nachrichtentyp:', message.type);
    }
}

