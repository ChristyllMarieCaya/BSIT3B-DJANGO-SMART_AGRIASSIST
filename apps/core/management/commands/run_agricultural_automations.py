import time
from django.core.management.base import BaseCommand
from apps.core.automation import run_all_agricultural_automations


class Command(BaseCommand):
    help = 'Executes the 12 automated agricultural processes (weather monitoring, alerts, crop stages, reminders)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run one automation cycle immediately and exit.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=300,
            help='Interval in seconds between automation cycles when running in daemon mode (default: 300s).',
        )

    def handle(self, *args, **options):
        once = options.get('once', False)
        interval = options.get('interval', 300)

        self.stdout.write(self.style.SUCCESS('SMART Agricultural Automation Engine initialized.'))

        if once:
            self.stdout.write('Executing one-shot automation cycle...')
            result = run_all_agricultural_automations()
            data = result.to_dict()
            self.stdout.write(self.style.SUCCESS(
                f"Completed in {data['duration_seconds']}s: "
                f"{data['users_processed']} users processed, "
                f"{data['weather_alerts_generated']} alerts generated, "
                f"{data['reminders_generated']} reminders generated, "
                f"{data['errors_count']} errors."
            ))
            return

        self.stdout.write(self.style.NOTICE(f'Running in continuous daemon mode (interval: {interval}s). Press Ctrl+C to stop.'))
        try:
            while True:
                result = run_all_agricultural_automations()
                data = result.to_dict()
                self.stdout.write(
                    f"[{data['completed_at']}] Cycle finished ({data['duration_seconds']}s): "
                    f"Users: {data['users_processed']}, Alerts: {data['weather_alerts_generated']}, "
                    f"Reminders: {data['reminders_generated']}, Errors: {data['errors_count']}"
                )
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Automation daemon stopped by user.'))
