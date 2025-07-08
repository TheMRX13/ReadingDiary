// Globale Variablen
let currentToken = '';
let currentServerUrl = '';
let currentPage = 'dashboard';

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
        // Erstelle temporäre Nachricht im Header oder Modal
        const tempMessage = document.createElement('div');
        tempMessage.className = `message ${type}`;
        tempMessage.textContent = message;
        tempMessage.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 16px;
            border-radius: 4px;
            color: white;
            font-weight: 500;
            z-index: 10000;
            max-width: 300px;
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
        
        // Nach 3 Sekunden automatisch entfernen
        setTimeout(() => {
            if (document.body.contains(tempMessage)) {
                document.body.removeChild(tempMessage);
            }
        }, 3000);
        
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
    // Dynamische Server-URL basierend auf dem aktuellen Host setzen
    const currentHost = window.location.hostname;
    const currentPort = window.location.port || '7443';
    currentServerUrl = `http://${currentHost}:${currentPort}`;
    
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
    document.getElementById('addBook').addEventListener('click', () => showAddBookModal());
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
        const response = await fetch(`${currentServerUrl}/api/login`, {
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
    localStorage.removeItem('token');
    currentToken = '';
    
    document.getElementById('loginScreen').style.display = 'flex';
    document.getElementById('mainApp').style.display = 'none';
    document.getElementById('password').value = '';
}

function showMainApp() {
    document.getElementById('loginScreen').style.display = 'none';
    document.getElementById('mainApp').style.display = 'flex';
    
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
async function loadBooks(search = '') {
    try {
        const books = await apiCall(`/books${search ? `?search=${encodeURIComponent(search)}` : ''}`);
        const booksListEl = document.getElementById('booksList');
        
        booksListEl.innerHTML = '';
        
        if (books.length > 0) {
            books.forEach(book => {
                const bookItem = createBookListItem(book);
                booksListEl.appendChild(bookItem);
            });
        } else {
            booksListEl.innerHTML = '<div class="book-item"><p>Keine Bücher gefunden.</p></div>';
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
        ? `${currentServerUrl}/uploads/covers/${book.cover_image}` 
        : (book.coverImage ? `${currentServerUrl}/uploads/covers/${book.coverImage}` : null);
    
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
    
    const statusBadge = (book.isRead || book.is_read)
        ? '<span class="status-badge read">Gelesen</span>'
        : '<span class="status-badge unread">Ungelesen</span>';
    
    const coverImageUrl = book.cover_image 
        ? `${currentServerUrl}/uploads/covers/${book.cover_image}` 
        : (book.coverImage ? `${currentServerUrl}/uploads/covers/${book.coverImage}` : null);
    
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
            ${statusBadge}
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
    
    let modalBody = '';
    
    if (isEdit) {
        // Detailansicht für existierende Bücher
        const progressPercent = book.pages ? Math.round(((book.readingProgress || book.reading_progress || 0) / book.pages) * 100) : 0;
        
        modalBody = `
            <div id="bookDetailView" data-book-id="${book.id}">
                <!-- Cover-Bereich -->
                <div class="book-section">
                    <div class="section-header">
                        <h3>Cover</h3>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="showCoverUpload(${book.id})">Cover hochladen</button>
                    </div>
                    <div class="cover-display">
                        ${(book.cover_image || book.coverImage) ? 
                            `<img src="${currentServerUrl}/uploads/covers/${book.cover_image || book.coverImage}" alt="Book Cover" class="book-cover-large">` : 
                            '<div class="no-cover"><i class="fas fa-book"></i><p>Kein Cover vorhanden</p></div>'
                        }
                    </div>
                    <div id="coverUploadForm" class="cover-upload-form" style="display: none;">
                        <div class="form-group">
                            <label for="coverFile">Cover-Datei wählen</label>
                            <input type="file" id="coverFile" accept="image/*" onchange="previewCover(this)">
                            <small>Unterstützte Formate: JPG, PNG, WebP</small>
                        </div>
                        <div id="coverPreview" class="cover-preview" style="display: none;">
                            <img id="previewImage" alt="Vorschau">
                        </div>
                        <div class="cover-upload-buttons">
                            <button type="button" class="btn btn-sm btn-secondary" onclick="cancelCoverUpload()">Abbrechen</button>
                            <button type="button" class="btn btn-sm btn-primary" onclick="uploadCover(${book.id})" disabled id="uploadCoverBtn">Cover hochladen</button>
                        </div>
                    </div>
                </div>

                <!-- Grundinformationen (nur anzeigen) -->
                <div id="basicInfoDisplay" class="book-section">
                    <div class="section-header">
                        <h3>Grundinformationen</h3>
                        <button type="button" class="btn btn-sm btn-secondary" onclick="toggleEditMode('basicInfo')">Bearbeiten</button>
                    </div>
                    <div class="book-info-grid">
                        <div><strong>Titel:</strong> ${escapeHtml(book.title || '')}</div>
                        <div><strong>Autor:</strong> ${escapeHtml(book.author || '')}</div>
                        <div><strong>Genre:</strong> ${escapeHtml(book.genre || '')}</div>
                        <div><strong>Seiten:</strong> ${book.pages || 0}</div>
                        <div><strong>Format:</strong> ${escapeHtml(book.format || '')}</div>
                        <div><strong>Verlag:</strong> ${escapeHtml(book.publisher || '')}</div>
                        <div><strong>Erscheinungsdatum:</strong> ${formatDate(book.publish_date || book.publishDate)}</div>
                        <div><strong>Reihe:</strong> ${escapeHtml(book.series || 'Keine')}</div>
                        <div><strong>Band:</strong> ${book.volume || 'Kein Band'}</div>
                        <div><strong>Status:</strong> ${(book.isRead || book.is_read) ? 'Gelesen' : 'Ungelesen'}</div>
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
                            <select id="bookGenre" required>
                                <option value="">Genre wählen</option>
                            </select>
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
                            <select id="bookPublisher" required>
                                <option value="">Verlag wählen</option>
                            </select>
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
                            <div class="checkbox-group">
                                <input type="checkbox" id="bookIsRead" ${(book.isRead || book.is_read) ? 'checked' : ''}>
                                <label for="bookIsRead">Gelesen</label>
                            </div>
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
                <!-- Cover Upload für neues Buch -->
                <div class="form-group">
                    <label for="newBookCover">Cover hochladen (optional)</label>
                    <input type="file" id="newBookCover" accept="image/*" onchange="previewNewBookCover(this)">
                    <small>Unterstützte Formate: JPG, PNG, WebP</small>
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
                        <select id="bookGenre" required>
                            <option value="">Genre wählen</option>
                        </select>
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
                        <select id="bookPublisher" required>
                            <option value="">Verlag wählen</option>
                        </select>
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
                        <div class="checkbox-group">
                            <input type="checkbox" id="bookIsRead" ${(book.isRead || book.is_read) ? 'checked' : ''}>
                            <label for="bookIsRead">Gelesen</label>
                        </div>
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
        loadGenresForSelect('bookGenre', book.genre);
    }
    if (document.getElementById('bookPublisher')) {
        loadPublishersForSelect('bookPublisher', book.publisher);
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
    try {
        const publishers = await apiCall('/publishers');
        const select = document.getElementById(selectId);
        
        publishers.forEach(publisher => {
            const option = document.createElement('option');
            option.value = publisher.name;
            option.textContent = publisher.name;
            option.selected = publisher.name === selectedValue;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Fehler beim Laden der Verlage:', error);
    }
}

// Genre und Publisher Management
async function addGenre() {
    const name = document.getElementById('newGenre').value.trim();
    if (!name) {
        showMessage(null, 'Bitte geben Sie einen Genre-Namen ein.', 'error');
        return;
    }
    
    try {
        await apiCall('/genres', {
            method: 'POST',
            body: { name }
        });
        
        document.getElementById('newGenre').value = '';
        loadGenreList();
        showMessage(null, 'Genre erfolgreich hinzugefügt!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
    }
}

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

async function addPublisher() {
    const name = document.getElementById('newPublisher').value.trim();
    if (!name) {
        showMessage(null, 'Bitte geben Sie einen Verlag-Namen ein.', 'error');
        return;
    }
    
    try {
        await apiCall('/publishers', {
            method: 'POST',
            body: { name }
        });
        
        document.getElementById('newPublisher').value = '';
        loadPublisherList();
        showMessage(null, 'Verlag erfolgreich hinzugefügt!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
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
        
        // Berechne gelesene Seiten
        let totalPagesRead = 0;
        if (stats.recentBooks && stats.recentBooks.length > 0) {
            totalPagesRead = stats.recentBooks
                .filter(book => book.is_read)
                .reduce((sum, book) => sum + (book.pages || 0), 0);
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
                    <div class="form-group">
                        <label for="newGenre">Neues Genre hinzufügen</label>
                        <div class="input-group">
                            <input type="text" id="newGenre" placeholder="Genre-Name">
                            <button class="btn btn-primary" onclick="addGenre()">Hinzufügen</button>
                        </div>
                    </div>
                    <div class="genre-list" id="genreList">
                        <p>Lade Genres...</p>
                    </div>
                </div>
            </div>
            
            <div class="settings-section">
                <h3>Verlage verwalten</h3>
                <div class="publisher-management">
                    <div class="form-group">
                        <label for="newPublisher">Neuen Verlag hinzufügen</label>
                        <div class="input-group">
                            <input type="text" id="newPublisher" placeholder="Verlag-Name">
                            <button class="btn btn-primary" onclick="addPublisher()">Hinzufügen</button>
                        </div>
                    </div>
                    <div class="publisher-list" id="publisherList">
                        <p>Lade Verlage...</p>
                    </div>
                </div>
            </div>
        `;
        
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

// Buch-Management-Funktionen
async function createBook() {
    try {
        const volumeValue = document.getElementById('bookVolume').value.trim();
        const bookData = {
            title: document.getElementById('bookTitle').value,
            author: document.getElementById('bookAuthor').value,
            genre: document.getElementById('bookGenre').value,
            pages: parseInt(document.getElementById('bookPages').value),
            format: document.getElementById('bookFormat').value,
            publisher: document.getElementById('bookPublisher').value,
            publish_date: document.getElementById('bookPublishDate').value,
            series: document.getElementById('bookSeries').value,
            volume: volumeValue ? parseInt(volumeValue) : 0,
            is_read: document.getElementById('bookIsRead').checked
        };
        
        const response = await apiCall('/books', {
            method: 'POST',
            body: bookData
        });
        
        // Cover upload if file selected
        const coverFile = document.getElementById('newBookCover');
        if (coverFile && coverFile.files.length > 0) {
            const formData = new FormData();
            formData.append('cover', coverFile.files[0]);
            
            await fetch(`${currentServerUrl}/api/books/${response.id}/cover`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${currentToken}`
                },
                body: formData
            });
        }
        
        closeModal();
        loadBooks();
        showMessage(null, 'Buch erfolgreich hinzugefügt!', 'success');
    } catch (error) {
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
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
        const bookData = {
            title: document.getElementById('bookTitle').value,
            author: document.getElementById('bookAuthor').value,
            genre: document.getElementById('bookGenre').value,
            pages: parseInt(document.getElementById('bookPages').value),
            format: document.getElementById('bookFormat').value,
            publisher: document.getElementById('bookPublisher').value,
            publish_date: document.getElementById('bookPublishDate').value,
            series: document.getElementById('bookSeries').value,
            volume: volumeValue ? parseInt(volumeValue) : 0,
            is_read: document.getElementById('bookIsRead').checked
        };
        
        await apiCall(`/books/${bookId}`, {
            method: 'PUT',
            body: bookData
        });
        
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

async function uploadCover(bookId) {
    const fileInput = document.getElementById('coverFile');
    if (!fileInput.files.length) {
        showMessage(null, 'Bitte wählen Sie eine Datei aus.', 'error');
        return;
    }
    
    try {
        const formData = new FormData();
        formData.append('cover', fileInput.files[0]);
        
        const response = await fetch(`${currentServerUrl}/api/books/${bookId}/cover`, {
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
        ? `${currentServerUrl}/uploads/covers/${item.cover_image}` 
        : (item.coverImage ? `${currentServerUrl}/uploads/covers/${item.coverImage}` : null);
    
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
            <!-- Cover Upload für Wunschliste -->
            <div class="form-group">
                <label for="newWishlistCover">Cover hochladen (optional)</label>
                <input type="file" id="newWishlistCover" accept="image/*" onchange="previewNewWishlistCover(this)">
                <small>Unterstützte Formate: JPG, PNG, WebP</small>
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
                    <select id="wishlistGenre">
                        <option value="">Genre wählen</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="wishlistPages">Seiten</label>
                    <input type="number" id="wishlistPages" min="1">
                </div>
                <div class="form-group">
                    <label for="wishlistPublisher">Verlag</label>
                    <select id="wishlistPublisher">
                        <option value="">Verlag wählen</option>
                    </select>
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
    loadGenresForSelect('wishlistGenre');
    loadPublishersForSelect('wishlistPublisher');
    
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
            
            // Cover upload if file selected
            const coverFile = document.getElementById('newWishlistCover');
            if (coverFile && coverFile.files.length > 0) {
                const formData = new FormData();
                formData.append('cover', coverFile.files[0]);
                
                await fetch(`${currentServerUrl}/api/wishlist/${response.id}/cover`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${currentToken}`
                    },
                    body: formData
                });
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

async function buyWishlistItem(itemId) {
    try {
        const item = await apiCall(`/wishlist/${itemId}`);
        
        // Zeige Modal für Formatauswahl
        const modalBody = `
            <div class="format-selection">
                <p>Buch wird zu "Meine Bücher" hinzugefügt. Bitte wählen Sie das Format:</p>
                <div class="format-options">
                    <div class="format-option" data-format="Hardcover">
                        <i class="fas fa-book"></i>
                        <span>Hardcover</span>
                    </div>
                    <div class="format-option" data-format="Paperback">
                        <i class="fas fa-book-open"></i>
                        <span>Paperback</span>
                    </div>
                    <div class="format-option" data-format="eBook">
                        <i class="fas fa-tablet-alt"></i>
                        <span>eBook</span>
                    </div>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                    <button type="button" class="btn btn-primary" id="confirmBuyBtn" disabled onclick="confirmBuyWishlistItem(${itemId})">Hinzufügen</button>
                </div>
            </div>
        `;
        
        showModal('Buch kaufen', modalBody);
        
        // Format Selection Event Listeners
        document.querySelectorAll('.format-option').forEach(option => {
            option.addEventListener('click', function() {
                document.querySelectorAll('.format-option').forEach(opt => opt.classList.remove('selected'));
                this.classList.add('selected');
                document.getElementById('confirmBuyBtn').disabled = false;
            });
        });
        
    } catch (error) {
        console.error('Error buying wishlist item:', error);
        showMessage(null, 'Fehler beim Laden des Wishlist-Items: ' + error.message, 'error');
    }
}

async function confirmBuyWishlistItem(itemId) {
    try {
        const selectedFormat = document.querySelector('.format-option.selected');
        if (!selectedFormat) {
            showMessage(null, 'Bitte wählen Sie ein Format aus.', 'error');
            return;
        }
        
        const format = selectedFormat.dataset.format;
        const item = await apiCall(`/wishlist/${itemId}`);
        
        // Convert wishlist item to book
        const bookData = {
            title: item.title,
            author: item.author,
            genre: item.genre || '',
            pages: item.pages || 0,
            publisher: item.publisher || '',
            publish_date: item.publish_date || '',
            series: item.series || '',
            volume: item.volume || 0,
            format: format,
            is_read: false
        };
        
        const newBook = await apiCall('/books', {
            method: 'POST',
            body: bookData
        });
        
        // Copy cover if exists
        if (item.cover_image) {
            try {
                await apiCall(`/wishlist/${itemId}/move-cover/${newBook.id}`, {
                    method: 'POST'
                });
            } catch (coverError) {
                console.warn('Cover konnte nicht übertragen werden:', coverError);
            }
        }
        
        // Delete from wishlist
        await apiCall(`/wishlist/${itemId}`, {
            method: 'DELETE'
        });
        
        closeModal();
        loadWishlist();
        showMessage(null, 'Buch erfolgreich zur Bibliothek hinzugefügt!', 'success');
    } catch (error) {
        console.error('Error buying wishlist item:', error);
        showMessage(null, 'Fehler beim Hinzufügen: ' + error.message, 'error');
    }
}

async function deleteWishlistItem(itemId) {
    if (!confirm('Sind Sie sicher, dass Sie diesen Eintrag löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/wishlist/${itemId}`, {
            method: 'DELETE'
        });
        
        loadWishlist();
        showMessage(null, 'Eintrag erfolgreich gelöscht!', 'success');
    } catch (error) {
        console.error('Error deleting wishlist item:', error);
        alert('Fehler beim Löschen: ' + error.message);
    }
}

// Quotes Funktionen
async function loadQuotes(search = '') {
    try {
        const quotes = await apiCall(`/quotes${search ? `?search=${encodeURIComponent(search)}` : ''}`);
        const quotesListEl = document.getElementById('quotesList');
        
        quotesListEl.innerHTML = '';
        
        if (quotes.length > 0) {
            quotes.forEach(quote => {
                const quoteItem = createQuoteItem(quote);
                quotesListEl.appendChild(quoteItem);
            });
        } else {
            quotesListEl.innerHTML = '<div class="quote-item"><p>Keine Zitate gefunden.</p></div>';
        }
    } catch (error) {
        console.error('Fehler beim Laden der Zitate:', error);
    }
}

function searchQuotes() {
    const search = document.getElementById('quotesSearch').value;
    loadQuotes(search);
}

function createQuoteItem(quote) {
    const item = document.createElement('div');
    item.className = 'quote-item';
    
    item.innerHTML = `
        <div class="quote-text">"${escapeHtml(quote.quote)}"</div>
        <div class="quote-meta">
            <div class="quote-source">${escapeHtml(quote.book)}, Seite ${quote.page}</div>
            <button class="btn btn-danger" onclick="deleteQuote(${quote.id})">
                <i class="fas fa-trash"></i> Löschen
            </button>
        </div>
    `;
    
    return item;
}

async function deleteQuote(quoteId) {
    if (!confirm('Sind Sie sicher, dass Sie dieses Zitat löschen möchten?')) {
        return;
    }
    
    try {
        await apiCall(`/quotes/${quoteId}`, {
            method: 'DELETE'
        });
        
        loadQuotes();
        showMessage(null, 'Zitat erfolgreich gelöscht!', 'success');
    } catch (error) {
        alert('Fehler beim Löschen: ' + error.message);
    }
}

function showAddQuoteModal() {
    const modalBody = `
        <form id="quoteForm">
            <div class="form-group">
                <label for="quoteText">Zitat *</label>
                <textarea id="quoteText" placeholder="Das Zitat..." required></textarea>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label for="quoteBook">Buch *</label>
                    <input type="text" id="quoteBook" placeholder="Buchtitel" required>
                </div>
                <div class="form-group">
                    <label for="quotePage">Seite *</label>
                    <input type="number" id="quotePage" placeholder="Seitenzahl" required min="1">
                </div>
            </div>
            
            <div style="display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px;">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Abbrechen</button>
                <button type="submit" class="btn btn-primary">Hinzufügen</button>
            </div>
        </form>
    `;
    
    showModal('Neues Zitat hinzufügen', modalBody);
    
    document.getElementById('quoteForm').onsubmit = async (e) => {
        e.preventDefault();
        
        try {
            const quoteData = {
                quote: document.getElementById('quoteText').value.trim(),
                book: document.getElementById('quoteBook').value.trim(),
                page: parseInt(document.getElementById('quotePage').value)
            };
            
            if (!quoteData.quote || !quoteData.book || !quoteData.page) {
                alert('Bitte füllen Sie alle Felder aus.');
                return;
            }
            
            await apiCall('/quotes', {
                method: 'POST',
                body: quoteData
            });
            
            closeModal();
            loadQuotes();
            showMessage(null, 'Zitat erfolgreich hinzugefügt!', 'success');
        } catch (error) {
            console.error('Error adding quote:', error);
            alert('Fehler beim Hinzufügen: ' + error.message);
        }
    };
}

// Fehlende showAddBookModal Funktion
function showAddBookModal() {
    const book = {}; // Leeres Buch für neues Buch
    showBookModal(book);
}

// Cover Preview Funktion für Wunschliste hinzufügen
function previewNewWishlistCover(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const preview = document.getElementById('newWishlistCoverPreview');
            const previewImage = document.getElementById('newWishlistPreviewImage');
            
            if (preview && previewImage) {
                previewImage.src = e.target.result;
                preview.style.display = 'block';
            }
        };
        reader.readAsDataURL(input.files[0]);
    }
}
