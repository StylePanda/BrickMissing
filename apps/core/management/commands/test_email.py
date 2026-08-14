from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test message through the configured Django email backend"

    def add_arguments(self, parser):
        parser.add_argument("recipient")

    def handle(self, *args, **options):
        recipient = options["recipient"].strip()
        if "@" not in recipient or "\n" in recipient or "\r" in recipient:
            raise CommandError("A valid recipient address is required")
        sent = send_mail("BrickMissing – E-Mail-Test", "Die Django E-Mail-Konfiguration funktioniert.", None, [recipient], fail_silently=False)
        if sent != 1:
            raise CommandError("Email backend did not accept the test message")
        self.stdout.write(self.style.SUCCESS("Test message accepted by email backend"))
