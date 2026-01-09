# Projektstatus (wird vom Agent gepflegt)

## Entscheidungen
- Template-Typen MVP:
  - DOCX: ja
  - PDF AcroForm: ja
  - OCR/Scan-PDF: nein (später)
- Reminder-Ausführung: Heroku Scheduler + Management Command (MVP)
 - Templates dienen als mandanten-spezifische Vorlagenbibliothek; Autofill kann sowohl auf Templates als auch auf beliebigen Kundendokumenten (Upload oder generiert) laufen.

## Fertig
- [x] Phase 0
- [x] Phase 1
- [x] Phase 2
- [x] Phase 3
- [x] Phase 4
- [x] Phase 5
- [ ] Phase 6

## Offene TODOs (kurz)
- keine offenen Punkte für Phase 0–4

## ENV Keys (aktuell genutzt)
- DJANGO_SETTINGS_MODULE
- SECRET_KEY
- DEBUG
- ALLOWED_HOSTS
- CSRF_TRUSTED_ORIGINS
- DATABASE_URL
- USE_S3
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_STORAGE_BUCKET_NAME
- AWS_S3_REGION_NAME
- MEDIA_URL
- EMAIL_BACKEND
- LOG_LEVEL
- SECURE_SSL_REDIRECT
- SECURE_HSTS_SECONDS
 - BREVO_API_KEY
 - BREVO_SENDER_EMAIL
 - BREVO_SENDER_NAME
