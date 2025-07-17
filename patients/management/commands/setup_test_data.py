from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from patients.models import Patient, FractionHistory
from datetime import date, timedelta

User = get_user_model()

class Command(BaseCommand):
    help = 'Створює тестові дані для Playwright тестів'

    def handle(self, *args, **options):
        self.stdout.write('Створення тестових даних...')
        
        # Створюємо тестового користувача
        user, created = User.objects.get_or_create(
            username='testuser',
            defaults={
                'password': 'testpass123',
                'role': 'doctor',
                'approved': True,
                'first_name': 'Тестовий',
                'last_name': 'Користувач',
                'is_staff': True,
                'is_active': True
            }
        )
        
        if created:
            user.set_password('testpass123')
            user.save()
            self.stdout.write('✅ Створено тестового користувача')
        else:
            self.stdout.write('ℹ️ Тестовий користувач вже існує')
        
        # Створюємо тестового пацієнта
        patient, created = Patient.objects.get_or_create(
            last_name='Тестовий',
            first_name='Пацієнт',
            defaults={
                'middle_name': 'Тестович',
                'diagnosis': 'Тестовий діагноз',
                'treatment_start_date': date.today() - timedelta(days=5),
                'total_fractions': 30,
                'dose_per_fraction': 2.0
            }
        )
        
        if created:
            self.stdout.write('✅ Створено тестового пацієнта')
        else:
            self.stdout.write('ℹ️ Тестовий пацієнт вже існує')
        
        # Створюємо тестові фракції
        for i in range(3):
            fraction, created = FractionHistory.objects.get_or_create(
                patient=patient,
                date=date.today() - timedelta(days=i+1),
                defaults={
                    'dose': 2.0,
                    'delivered': True,
                    'confirmed_by_doctor': True
                }
            )
            
            if created:
                self.stdout.write(f'✅ Створено фракцію {i+1}')
        
        self.stdout.write(self.style.SUCCESS('🎉 Тестові дані створено успішно!'))
        self.stdout.write('Логін: testuser')
        self.stdout.write('Пароль: testpass123') 