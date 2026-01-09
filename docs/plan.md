# Implementierungsplan (phasenweise)

## Phase 0 – Projektgrundlagen
**Ziel:** Repo-Setup, Django-Projekt, ENV, Heroku-ready Grundkonfig.
- Custom User Model + Rollen
- Settings Split (base/prod), Whitenoise
- PostgreSQL config
- Storage abstraction (local vs S3 stub)
**Done wenn:** App startet lokal + migrations laufen + Login-Seite erreichbar.

## Phase 1 – Dashboard-Layout & Auth
- Tailwind + Flowbite + Basislayout (Sidebar/Topbar)
- Login/Logout
- Broker Dashboard Startseite (KPIs dummy)
**Done wenn:** Broker kann sich einloggen, Dashboard sieht seriös aus.

## Phase 2 – Kundenverwaltung + Invite Flow
- Customer CRUD (Broker only)
- Invite-Link generieren (Token, expiry)
- Customer Signup/Link-Verknüpfung + Selbstauskunft Formular
**Done wenn:** Endkunde per Link Account erstellt & Daten gespeichert sind.

## Phase 3 – Dokumente & Templates
- DocumentTemplate CRUD (DOCX + PDF AcroForm) als zentrale Vorlagen-Bibliothek (mandanten-spezifisch, nicht kunden-gebunden)
- CustomerDocument: Upload (ohne Template-Pflicht) + Zuordnung zum Kunden
- Kundenseite: Dokument-Tab (Liste, Status, Download, Löschen)
**Done wenn:** Broker Templates anlegen kann und kundenspezifische Dokumente verwaltet (unabhängig von Templates).

## Phase 4 – Autofill Engine (KI-gestützt)
- Field schema parser
- Mapping Service (LLM optional via ENV, sonst Fallback)
- Renderer:
  - DOCX via docxtpl
  - PDF AcroForm via pypdf
- Mapping Report + Speicherung
**Done wenn:** “Kunde wählen → (Template **oder** bestehendes Kundendokument) wählen → generiertes bearbeitbares Dokument”.

## Phase 5 – Reminder + Brevo
- ReminderRule UI
- `send_due_reminders` Management Command
- Brevo Provider + Logs
- Heroku Scheduler Doku
  - Heroku Scheduler Job anlegen, der 1x täglich (z. B. 08:00 UTC) läuft
  - Command: `python manage.py send_due_reminders`
  - Umgebung: identisch zu Web-Dyno, z. B. `DJANGO_SETTINGS_MODULE=config.settings.prod`
**Done wenn:** Reminder automatisiert rausgehen + Logs sichtbar.

## Phase 6 – Tests & Hardening
- pytest-django smoke tests
- permission tests (tenant isolation)
- Rate limiting Invite
- README final + Heroku checklist
