from django.core.management.base import BaseCommand
from consultations import services
from consultations.models import ConsultationSession


class Command(BaseCommand):
    help = "Bill all in-progress sessions for their elapsed minutes. Schedule it every minute (cron)."

    def handle(self, *args, **options):
        ids = list(ConsultationSession.objects
                   .filter(status=ConsultationSession.Status.IN_PROGRESS)
                   .values_list("pk", flat=True))
        for session_id in ids:
            services.bill_session(session_id)
        self.stdout.write(self.style.SUCCESS(f"Billed {len(ids)} session(s)."))
