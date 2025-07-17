from django.core.management.base import BaseCommand
from patients.models import Patient
from patients.services import recalculate_discharge_date


class Command(BaseCommand):
    help = 'Оновлює дати виписки для всіх пацієнтів на основі їхніх фракцій'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показати що буде змінено без збереження',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Отримуємо всіх пацієнтів з фракціями
        patients_with_fractions = Patient.objects.filter(
            fractions__isnull=False
        ).distinct()
        
        self.stdout.write(f"Знайдено {patients_with_fractions.count()} пацієнтів з фракціями")
        
        updated_count = 0
        for patient in patients_with_fractions:
            old_discharge_date = patient.discharge_date
            
            if not dry_run:
                new_date = recalculate_discharge_date(patient)
            else:
                # Для dry-run просто розраховуємо дату без збереження
                last_fraction = patient.fractions.order_by('date').last()
                new_date = last_fraction.date if last_fraction else None
            
            if new_date and new_date != old_discharge_date:
                updated_count += 1
                self.stdout.write(
                    f"Пацієнт: {patient.full_name} - "
                    f"Стара дата: {old_discharge_date or 'Не встановлена'} - "
                    f"Нова дата: {new_date}"
                )
            elif new_date == old_discharge_date:
                self.stdout.write(
                    f"Пацієнт: {patient.full_name} - "
                    f"Дата вже правильна: {old_discharge_date}"
                )
            else:
                self.stdout.write(
                    f"Пацієнт: {patient.full_name} - "
                    f"Не вдалося розрахувати дату виписки"
                )
        
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: Було б оновлено {updated_count} пацієнтів"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Успішно оновлено {updated_count} пацієнтів"
                )
            ) 