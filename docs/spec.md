# Immobilien-Tool – Spezifikation (Django)

## 1. Ziel
Webbasierte Software für Immobilienmakler (B2B), um Endkunden (B2C) zu verwalten und Dokumente anhand vorhandener Kundendaten KI-gestützt so weit wie möglich automatisch auszufüllen und als **bearbeitbare Datei** bereitzustellen.

Hosting: Heroku.

## 2. Rollen & Berechtigungen
### Rollen
- **BROKER (Makler)**
- **CUSTOMER (Endkunde)**

### Grundregeln (Multi-Tenant)
- Ein Makler sieht **nur** seine eigenen Kunden, Dokumente, Templates, Reminder-Regeln und Logs.
- Endkunden sehen **nur** ihre eigenen Daten und ggf. ihnen zugewiesene Dokumente.

## 3. Kernfunktionen (Must-have)
### 3.1 Makler-Dashboard
- Login Makler
- Kunden CRUD
- Kundenliste mit Suche/Filter (Name, Status, letzter Kontakt, offene Dokumente, fällige Reminders)
- Kundendetailseite mit Tabs: Überblick, Selbstauskunft, Dokumente, Reminders

### 3.2 Kunden-Selbstauskunft per Link (Invite)
- Makler kann Invite-Link erzeugen (Token, Ablauf z. B. 14 Tage)
- Endkunde öffnet Link:
  - erstellt Account oder verknüpft bestehenden Account
  - füllt Selbstauskunft aus (validiert, strukturiert)
- Rate limiting + Token expiry + optional Single-Use

### 3.3 Dokumenten-Management
- Mehrere Dokumente je Kunde (Uploads + generierte Dokumente)
- Dokument-Templates je Makler (z. B. Bank-/Selbstauskunft-Formulare) als **zentrale Vorlagen-Bibliothek** (losgelöst von einzelnen Kunden)

### 3.4 Dokumenten-Autofill (KI-gestützt)
Ziel: Makler wählt Kunde + (a) Template **oder** (b) bestehendes Kundendokument → System füllt Felder automatisch, soweit Daten vorhanden sind.

**Wichtig:** KI soll primär das **Mapping** zwischen Template-Feldern und Kundendaten bestimmen; das Ausfüllen erfolgt deterministisch.

#### Unterstützte Template-Typen (MVP)
- **DOCX Templates** (empfohlen für Verträge/standardisierte Formulare)
- **Fillable PDF (AcroForm)** (empfohlen für Bankformulare)

#### Output
- Bearbeitbare Datei:
  - bei DOCX: generiertes DOCX
  - bei AcroForm: ausgefülltes, weiter bearbeitbares PDF (nicht flatten)

#### KI-Mapping (MVP-Ansatz)
- Jedes Template hat idealerweise ein `field_schema` (JSON) mit:
  - Feldname/ID im Template
  - Label (falls vorhanden)
  - Datentyp (text/date/number/boolean)
  - optional Beispielwert/Regeln
- LLM (optional per ENV) erzeugt Mapping auf Basis von Template oder bestehendem Dokument:
  - `template_field` → `customer_data_key`
  - plus `transform` (z. B. Datumsformat)
  - plus `confidence`
- Fallback ohne LLM:
  - fuzzy matching (string similarity) + Hand-Mapping durch Makler in UI

#### Quality / Safety
- Keine “Erfindung” von Daten: wenn Daten fehlen → Feld bleibt leer + Report “missing”
- Pro Lauf wird ein Mapping-Report gespeichert (welche Felder gefüllt, welche fehlen, confidence)

### 3.5 E-Mail-Erinnerungen (Brevo)
- Reminder-Regeln je Makler (z. B. 14 Tage nach “Dokument versendet”)
- Täglicher Job:
  - prüft fällige Reminders
  - sendet via Brevo
  - loggt Ergebnis (ReminderLog)
- Job-Ausführung über:
  - Heroku Scheduler + Management Command (MVP) ODER
  - Celery Beat (Pro)

## 4. Non-Functional Requirements
- Security: CSRF, sichere Token, permissions, audit/logging light
- Performance: Background Jobs für Autofill/Generierung
- Datenhaltung: PostgreSQL, Dateiablage über S3 (prod)
- Deployment: Heroku (12-factor, ENV-config)
- Tests: pytest-django (smoke + critical paths)

## 5. Empfohlener Tech-Stack
### Backend
- Django 5, Python 3.12
- PostgreSQL (+ optional pgvector)
- Celery + Redis (Worker für Autofill, Reminders, große Uploads)

### Dokumente
- DOCX: `docxtpl` (+ optional `python-docx`)
- PDF (AcroForm): `pypdf` (oder pdfrw wenn nötig)

### KI
- OpenAI (oder austauschbar) mit **Structured JSON Output**
- optional Embeddings + pgvector (besseres Matching bei vielen Templates)

### Frontend
- Django Templates
- Tailwind CSS
- Flowbite (oder Tabler UI) Komponenten
- HTMX (Search, Modals, Inline Updates)

## 6. Datenmodell (Vorschlag)
### User (Custom)
- email, password, role (BROKER/CUSTOMER), is_active, created_at

### BrokerProfile
- user (1:1), firm_name, phone, address, brevo_sender_name/email, created_at

### CustomerProfile
- user (optional 1:1, falls Customer Account existiert)
- broker (FK)
- status (new/in_progress/complete)
- personal data fields (name, address, dob, etc.)
- finance/employment fields (vereinbart im MVP-Formular)
- updated_at

### CustomerInvite
- broker (FK), customer (FK)
- token, expires_at, used_at, created_at

### DocumentTemplate
- broker (FK)
- name, type (DOCX/PDF_ACROFORM)
- file (template)
- field_schema (JSON)
- created_at
> Hinweis: Templates sind mandanten-spezifische, wiederverwendbare Vorlagen und nicht direkt an Kunden gebunden.

### CustomerDocument
- broker (FK), customer (FK)
- template (FK, optional – nur gesetzt, wenn aus einem Template entstanden)
- uploaded_file (optional)
- generated_file (optional)
- status (draft/sent/completed)
- sent_to_customer_at (datetime, optional)
- created_at

### ReminderRule
- broker (FK)
- trigger_event (z. B. DOCUMENT_SENT)
- days_after (int)
- brevo_template_id (optional) / subject/body fallback
- enabled (bool)

### ReminderLog
- broker (FK), customer (FK), document (FK optional), rule (FK)
- due_at, sent_at, status, provider_response_id, error_text

## 7. Wichtige Flows
### Flow A: Kunde anlegen + Invite-Link senden
1) Broker erstellt CustomerProfile
2) Broker klickt “Invite-Link erzeugen”
3) System generiert token + expiry
4) Broker sendet Link manuell oder systemseitig via Mail (später)

### Flow B: Endkunde Selbstauskunft
1) Öffnet Invite-Link
2) Setzt Passwort → Customer Account wird erstellt/verknüpft
3) Füllt Selbstauskunft aus → CustomerProfile aktualisiert

### Flow C: Dokument Autofill
1) Broker wählt Customer + **entweder**
   - Template (neues Kundendokument aus globaler Vorlage) **oder**
   - bestehendes Kundendokument (Upload oder bereits generiert)
2) System erzeugt Mapping (LLM oder Fallback) auf Basis des gewählten Templates/Basisdokuments
3) System generiert ausgefüllte Datei (DOCX/PDF)
4) Speichert CustomerDocument.generated_file + Report
5) Broker kann downloaden / “als versendet markieren”

### Flow D: Reminder
1) Broker markiert Dokument als “versendet”
2) Regel: X Tage danach Reminder fällig
3) Täglicher Job sendet Mail via Brevo → ReminderLog

## 8. Definition of Done (MVP)
- Broker kann Kunden anlegen/verwalten
- Endkunde kann per Link Account erstellen und Daten eintragen
- Broker kann Template hochladen und Kundendokument generieren (Autofill)
- Reminder Job läuft täglich und sendet via Brevo
- Deployment auf Heroku dokumentiert
