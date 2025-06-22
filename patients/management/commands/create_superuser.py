from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from patients.models import User

class Command(BaseCommand):
    help = 'Створює суперкористувача для системи'

    def handle(self, *args, **options):
        User = get_user_model()
        
        # Перевіряємо, чи існує вже суперкористувач
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING('Суперкористувач вже існує'))
            return
        
        # Створюємо суперкористувача
        try:
            user = User.objects.create_superuser(
                username='admin',
                password='admin123',
                role='admin',
                approved=True,
                is_staff=True,
                is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'Суперкористувач створено успішно!\nЛогін: admin\nПароль: admin123')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Помилка створення суперкористувача: {e}')
            ) 