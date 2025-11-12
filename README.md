# 📚 Reading Diary

Ein lokales Buchverwaltungssystem mit Web-Interface für Windows.

![License](https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Web-green?style=for-the-badge)

## ✨ Features

### 📖 **Buchverwaltung**
- Vollständige Buchdatenbank mit Metadaten (Titel, Autor, ISBN, Genre, Verlag, etc.)
- ISBN-Scanner (Kamera)* und manuelle ISBN-Eingabe
- Cover-Upload und automatischer Cover-Download via ISBN (Google Books API)
- Serienorganisation mit Bandnummern
- Lesefortschritt-Tracking mit Historie
- Bewertungssystem (Sterne, Spice-Level, Spannung)
- Markdown-Rezensionen
- Status-Tracking (Ungelesen, Am Lesen, Gelesen)

**\*Hinweis:** ISBN-Scanner (Kamera-Zugriff) benötigt HTTPS

### 🎯 **Wunschliste & Zitate**
- Bücher zur Wunschliste hinzufügen mit vollständigen Metadaten
- "Gekauft"-Workflow mit automatischer Übernahme in die Bibliothek
- Cover-Übernahme von Wunschliste zu Buch
- Formatauswahl (Taschenbuch, Hardcover, E-Book, Hörbuch)
- Zitate-Sammlung mit Buch- und Seitenangaben

### 📊 **Statistiken**
- Dashboard mit Buchanzahl und gelesenen Seiten
- Aktueller Lesefortschritt
- Genre- und Verlagsstatistiken
- Leseziel-Tracking (jährlich)

### 🔄 **Echtzeit-Updates**
- WebSocket-Integration für Live-Updates
- Automatische Synchronisation über mehrere Browser/Geräte

### 📱 **Progressive Web App (PWA)***
- Installierbar auf Desktop und Mobile
- Responsive Design für alle Bildschirmgrößen
- App-Icons für alle Plattformen

**\*Hinweis:** PWA-Features wie Service Worker und Offline-Funktionalität benötigen HTTPS. Über HTTP (Standard) funktioniert die App als normale Web-Anwendung.

## ⚡ **Performance**

- RAM: ~100-200 MB | CPU: <1% | Größe: ~100 MB | Start: <10s

## 📦 **Installation**

1. Unter Release Reading Diary Downloaden
2. Programm starten 
3. Server über GUI starten
4. Web-Interface per: `http://localhost:7443` aufrufen oder direkt im Programm "Web-Interface öffnen" Klicken
5. Anmelden mit dem Standard Passwort `admin123` oder es vorher im Programm ändern

## 🛠️ **Technisch**

### Backend
- **Sprache**: Go 1.21+
- **Web-Framework**: Gin (HTTP-Router & Middleware)
- **GUI**: Fyne v2 (Desktop-GUI mit Live-Logging)
- **Datenbank**: SQLite mit GORM ORM
- **Echtzeit**: Gorilla WebSocket für Live-Updates
- **API-Integration**: Google Books API (ISBN-Suche)

### Frontend
- **Technologie**: Vanilla JavaScript (kein Framework)
- **Styling**: CSS3 mit modernem Design
- **Icons**: Font Awesome 6.0
- **PWA**: Service Worker, Web App Manifest

### Systemanforderungen
- **OS**: Windows 10/11 (x64)
- **RAM**: Minimum 2GB
- **Speicher**: ~100MB + Datenbank
- **Browser**: Chrome, Firefox, Edge, Safari (für Web-Interface)
- **Netzwerk**: Kein Internet erforderlich (läuft lokal außer ISBN Suche)

## 🔐 **Sicherheit**

- Lokale Datenspeicherung (keine Cloud)
- Passwort-Schutz für Web-Interface
- Keine Benutzerregistrierung nötig
- Kompatibel mit nginx


## 🔧 Geplante Features

### Clients
- [ ] **Native Android/iOS Apps**: React Native oder Flutter für mobile Geräte
- [x] **Windows Desktop-Programm**
- [ ] **Linux/macOS Support**: Plattformübergreifende Desktop-Version

### Daten & Backup
- [ ] **Automatische Backups**: Regelmäßige SQLite-DB Sicherungen
- [ ] **Export/Import**: JSON/CSV Export für Bücher, Statistiken und Zitate
- [ ] **Goodreads-Import**: Bücherlisten von Goodreads importieren

### E-Book Verwaltung
- [ ] **E-Book Reader**: EPUB/PDF direkt in der App lesen
- [ ] **Verleihsystem**: Digitale E-Books verleihen und verwalten
- [ ] **Virtuelle Bibliothek**: Eigene E-Book-Sammlung organisieren

### Erweiterte Funktionen
- [ ] **Buchserien-Management**: Übersichtliche Darstellung von Buchreihen
- [ ] **Thematische Leselisten**: Eigene Listen erstellen (z.B. "Sommer 2025", "Lieblinge")
- [ ] **Verleihfunktion**: Tracking an wen welches Buch verliehen wurde
- [ ] **Lesezeit-Tracking**: Wie lange brauche ich für ein Buch?
- [ ] **Notizen während des Lesens**: Zusätzliche Anmerkungen zu Kapiteln

### Statistiken & Visualisierung
- [ ] **Jahresübersicht**: Gelesene Seiten pro Monat mit Diagrammen
- [ ] **Genre-Verteilung**: Pie Charts der am meisten gelesenen Genres
- [ ] **Lesegeschwindigkeit**: Durchschnittliche Seiten pro Tag/Woche
- [ ] **Zeitachse**: Chronologische Übersicht aller gelesenen Bücher
- [ ] **Verbessertes Ziel-Tracking**: Detaillierte Fortschrittsvisualisierung

### Benutzer & Sicherheit
- [ ] **Multi-User-Support**: Mehrere Benutzer mit eigenen Bibliotheken
- [ ] **Passwort-Hashing**: Sichere Passwort-Speicherung (aktuell Klartext)
- [ ] **JWT-Token-Auth**: Moderne Authentifizierung statt Bearer-Token

### UX & Performance
- [ ] **Drag & Drop**: Cover-Bilder per Drag & Drop hochladen
- [ ] **Keyboard Shortcuts**: Schnellzugriff (z.B. N für neues Buch)
- [ ] **Bulk-Operations**: Mehrere Bücher gleichzeitig bearbeiten/löschen
- [ ] **Lazy Loading**: Bilder erst laden wenn sichtbar
- [ ] **API-Pagination**: Große Datensätze in Seiten aufteilen
- [ ] **Caching**: Schnellere Ladezeiten durch Response-Caching
---

# Discord

Betrete jetzt auch meinen Discord. Hier bekomsmt du hilfe und rat für alles und hast direkten kontakt zum Entwickler 
[Jetzt Betreten](https://discord.gg/T5yPWAbRdz)

**📚 Reading Diary** - *Lokale Buchverwaltung für Windows*

*Entwickelt mit ❤️ für Buchliebhaber*
