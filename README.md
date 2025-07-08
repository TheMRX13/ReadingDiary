# 📚 Reading Diary

Ein lokales Buchverwaltungssystem mit Web-Interface für Windows.

![License](https://img.shields.io/badge/License-Proprietary-red?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Web-green?style=for-the-badge)

## ✨ Features

### 📖 **Buchverwaltung**
- Vollständige Buchdatenbank mit Metadaten
- Cover-Upload und Serienorganisation
- Lesefortschritt-Tracking mit Historie
- Bewertungssystem (Sterne, Spice-Level, Spannung)
- Markdown-Rezensionen

### 🎯 **Wunschliste & Zitate**
- Bücher zur Wunschliste hinzufügen
- "Gekauft"-Workflow mit Formatauswahl
- Zitate-Sammlung mit Seitenangaben

### 📊 **Statistiken**
- Dashboard mit Buchanzahl und gelesenen Seiten
- Genre- und Verlagsstatistiken
- Leseziel-Tracking (jährlich)

## 🚀 **Komponenten**

- **Go-Server** mit Fyne-GUI (Port 7443)
- **Web-Interface** - responsive, passwort-geschützt
- **SQLite-Datenbank** - lokal gespeichert

## ⚡ **Performance**

- RAM: ~20-150 MB | CPU: <1% | Größe: ~60 MB | Start: <10s

## 📦 **Installation**

1. Unter Release Reading Diary Downloaden
2. Programm starten 
3. Server über GUI starten
4. Web-Interface: `http://localhost:7443`
5. Anmelden mit `admin123` oder Passwort ändern

## 🛠️ **Technisch**

- **Backend**: Go, Gin, SQLite, GORM, Fyne
- **Frontend**: Vanilla JavaScript, CSS, FontAwesome
- **Systemanforderungen**: Windows 10/11, 2GB RAM, 100MB Speicher

## 🔐 **Sicherheit**

- Lokale Datenspeicherung (keine Cloud)
- Passwort-Schutz für Web-Interface
- Keine Benutzerregistrierung nötig

---

**📚 Reading Diary** - *Lokale Buchverwaltung für Windows*

*Entwickelt mit ❤️ für Buchliebhaber*
