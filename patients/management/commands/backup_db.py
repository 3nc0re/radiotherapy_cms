import os
import subprocess
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from supabase import create_client, Client

class Command(BaseCommand):
    help = 'Створює резервну копію бази даних Supabase та завантажує її у Supabase Storage.'

    def handle(self, *args, **options):
        # --- 1. Створення локальної копії ---
        local_backup_path = self.create_local_backup()
        if not local_backup_path:
            return

        # --- 2. Завантаження у Supabase Storage ---
        self.upload_to_supabase_storage(local_backup_path)

        # --- 3. Очищення ---
        os.remove(local_backup_path)
        self.stdout.write(self.style.SUCCESS(f"Локальний файл {local_backup_path} видалено."))

    def create_local_backup(self):
        db_settings = settings.DATABASES['default']
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        
        # Використовуємо тимчасову папку, яку потім видалимо
        temp_dir = 'temp_backups'
        os.makedirs(temp_dir, exist_ok=True)
        
        backup_file_name = f'db_backup_{timestamp}.sql'
        local_backup_path = os.path.join(temp_dir, backup_file_name)
        
        self.stdout.write("Створення резервної копії бази даних Supabase...")
        
        db_pass = db_settings['PASSWORD']
        db_host = db_settings['HOST']
        db_user = db_settings['USER']
        db_name = db_settings['NAME']
        
        env = os.environ.copy()
        env['PGPASSWORD'] = db_pass

        # Команда pg_dump для підключення до Supabase
        command = [
            'pg_dump',
            f'--host={db_host}',
            f'--username={db_user}',
            f'--dbname={db_name}',
            '--clean', # Додає команди для очищення об'єктів перед створенням
            '--format=c' # Стиснений, надійний формат
        ]

        try:
            with open(local_backup_path, 'wb') as f:
                process = subprocess.run(command, check=True, env=env, stdout=f, stderr=subprocess.PIPE)
            self.stdout.write(self.style.SUCCESS(f"Локальну копію успішно створено: {local_backup_path}"))
            return local_backup_path
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR("Помилка: 'pg_dump' не знайдена. Переконайтеся, що на сервері Render встановлено PostgreSQL buildpack."))
        except subprocess.CalledProcessError as e:
            self.stderr.write(self.style.ERROR("Помилка під час створення резервної копії:"))
            self.stderr.write(e.stderr.decode())
        
        return None

    def upload_to_supabase_storage(self, file_path):
        self.stdout.write("Завантаження резервної копії у Supabase Storage...")
        
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_SERVICE_KEY')
        bucket_name = 'backups' # Назва сховища, яке ви створите в Supabase

        if not url or not key:
            self.stderr.write(self.style.ERROR("Змінні середовища SUPABASE_URL та SUPABASE_SERVICE_KEY не налаштовано."))
            return

        try:
            supabase: Client = create_client(url, key)
            
            # Перевіряємо, чи існує bucket, і створюємо, якщо ні
            buckets = supabase.storage.list_buckets()
            if not any(b.name == bucket_name for b in buckets):
                supabase.storage.create_bucket(bucket_name, {"public": False})
                self.stdout.write(f"Створено нове сховище (bucket): {bucket_name}")

            destination_path = f'{os.path.basename(file_path)}'

            with open(file_path, 'rb') as f:
                supabase.storage.from_(bucket_name).upload(path=destination_path, file=f)
            
            self.stdout.write(self.style.SUCCESS(f"Файл успішно завантажено у сховище '{bucket_name}'."))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Помилка під час роботи з Supabase Storage: {e}")) 