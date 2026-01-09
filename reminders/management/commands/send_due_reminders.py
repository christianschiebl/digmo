import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from reminders.brevo import BrevoEmailProvider, BrevoEmailProviderError
from reminders.models import ReminderLog


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sendet fällige Reminder-E-Mails über Brevo und aktualisiert ReminderLogs."

    def handle(self, *args, **options):
        provider = BrevoEmailProvider()
        if not provider.is_configured():
            self.stderr.write(
                self.style.WARNING(
                    "BREVO_API_KEY ist nicht gesetzt. Reminder-Versand wird übersprungen."
                )
            )
            return

        now = timezone.now()
        pending_logs = (
            ReminderLog.objects.filter(
                status=ReminderLog.Status.PENDING,
                due_at__lte=now,
            )
            .select_related("broker", "customer", "document", "rule")
            .order_by("due_at")
        )

        total = pending_logs.count()
        if total == 0:
            self.stdout.write("Keine fälligen Reminder gefunden.")
            return

        sent_count = 0
        failed_count = 0

        for log in pending_logs:
            rule = log.rule

            # Falls Regel deaktiviert wurde, Reminder als fehlgeschlagen markieren.
            if not rule.enabled:
                log.mark_failed("Regel wurde deaktiviert.")
                failed_count += 1
                continue

            customer = log.customer
            broker = log.broker
            document = log.document

            to_email = customer.email
            to_name = f"{customer.first_name} {customer.last_name}".strip()

            # Default-Subject/Body, falls Rule-Felder leer sind.
            subject = (
                rule.subject
                or "Erinnerung zu Ihren Unterlagen bei Ihrem Immobilienmakler"
            )

            if rule.body:
                body = rule.body
            else:
                body = (
                    f"Hallo {customer.first_name},\n\n"
                    "dies ist eine Erinnerung an das Dokument, das wir Ihnen zugesendet haben.\n\n"
                    "Viele Grüße\n"
                    f"Ihr Makler ({broker.email})"
                )

            # Parameter, die in Brevo-Templates verwendet werden können.
            params = {
                "customer_first_name": customer.first_name,
                "customer_last_name": customer.last_name,
                "customer_email": customer.email,
                "customer_full_name": f"{customer.first_name} {customer.last_name}".strip(),
                "broker_email": broker.email,
            }
            if document is not None:
                params["document_id"] = document.id
                params["document_filename"] = document.filename

            try:
                if rule.uses_brevo_template:
                    try:
                        template_id = int(rule.brevo_template_id)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        raise BrevoEmailProviderError(
                            f"Ungültige Brevo Template-ID: {rule.brevo_template_id!r}"
                        )

                    provider_response_id = provider.send_email(
                        to_email=to_email,
                        to_name=to_name,
                        template_id=template_id,
                        params=params,
                    )
                else:
                    provider_response_id = provider.send_email(
                        to_email=to_email,
                        to_name=to_name,
                        subject=subject,
                        text_content=body,
                    )
            except BrevoEmailProviderError as exc:
                logger.exception(
                    "Versand des Reminders fehlgeschlagen (Log-ID=%s): %s",
                    log.id,
                    exc,
                )
                log.mark_failed(str(exc))
                failed_count += 1
                continue

            log.mark_sent(provider_response_id)
            sent_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Reminder-Versand abgeschlossen: gesendet={sent_count}, fehlgeschlagen={failed_count}, gesamt={total}."
            )
        )



