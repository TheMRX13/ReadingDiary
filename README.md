# 📚 Reading Diary

Eine persönliche Bücherverwaltung als Web-App – lokal gehostet, mobilfreundlich, mit Dark Mode.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.0.3-black?logo=flask)
![SQLite](https://img.shields.io/badge/SQLite-3-blue?logo=sqlite)

---

## Features

- 📖 **Bücherverwaltung** – Bücher hinzufügen (manuell, per ISBN oder Kamera-Scan), bearbeiten, löschen
- 🎧 **Hörbuch-Support** – Hörfortschritt in Prozent tracken, eigenes Badge „Am Hören"
- 📊 **Statistiken** – Gelesene Bücher, Seiten, Zitate, Lesesträhne, Höchste Strähne, Jahresrückblick
- 🎯 **Leseziele** – Bücher- oder Seitenziele pro Monat/Jahr setzen
- ⭐ **Bewertungen** – Sterne, Spice, Spannung, Fiction/Non-Fiction
- 📝 **Rezensionen & Notizen** – Rich-Text-Rezensionen und Kapitelnotizen pro Buch
- 💬 **Zitate** – Lieblingszitate speichern
- 📚 **Serien & Regale** – Bücher in Serien und eigene Regale organisieren
- 🛒 **Wunschliste** – Bücher vormerken, per Klick in die Bibliothek verschieben
- 🔥 **Lesesträhne** – Tägliche Lesesträhne im Seitenmenü
- 🌙 **Dark Mode** – Umschaltbar per Toggle
- 📱 **PWA** – Als App auf dem Homescreen installierbar
- 🔒 **Login-Schutz** – Einfacher Passwortschutz
- 📤 **CSV-Export** – Bibliothek exportieren
- 🔧 **Einstellungen** – Features einzeln ein-/ausblenden

---

## Installation

### Voraussetzungen
- **Python 3.10+** – [https://www.python.org/downloads/](https://www.python.org/downloads/)
- pip (wird mit Python mitgeliefert)

> **Kein Python installiert?**  
> Öffne die Seite oben, lade den Installer für dein Betriebssystem herunter und führe ihn aus.  
> **Windows:** Haken bei „Add Python to PATH" setzen, dann auf „Install Now" klicken.  
> Danach ein neues Terminal öffnen und `python --version` eingeben – wenn eine Versionsnummer erscheint, ist alles bereit.

### Setup

1. Oben rechts auf dieser Seite auf **Code → Download ZIP** klicken
2. ZIP entpacken
3. `app.py` **doppelklicken** – Abhängigkeiten werden automatisch installiert

Die App ist dann unter **http://localhost:7443** erreichbar.

---

## Konfiguration

Das Standard-Passwort beim ersten Start ist `admin`. Es kann in den **Einstellungen** geändert werden.

Die Datenbank (`reading_diary.db`) wird automatisch beim ersten Start erstellt.

---

## Technologie

| Komponente | Technologie |
|---|---|
| Backend | Flask 3.0.3 |
| Datenbank | SQLite (via `sqlite3`) |
| Frontend | Bootstrap 5.3, Font Awesome 6 |
| Charts | Chart.js 4 |
| Editor | Quill.js |
| ISBN-Scan | html5-qrcode |

---

## Lizenz

MIT License – frei nutzbar und anpassbar.
