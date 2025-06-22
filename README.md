# Radiotherapy CMS

Система управління пацієнтами для радіотерапії. Django-додаток для ведення обліку пацієнтів, фракцій лікування та медичної документації.

## Функціональність

- Управління пацієнтами (додавання, редагування, архівування)
- Ведення фракцій лікування
- Система ролей (лікар, медсестра, адміністратор)
- Медична документація
- Архівування пацієнтів
- Пошук та фільтрація

## Технології

- Django 5.2.3
- PostgreSQL
- Bootstrap
- Python 3.11+

## Локальне розгортання

1. Клонуйте репозиторій:
```bash
git clone https://github.com/your-username/radiotherapy_cms.git
cd radiotherapy_cms
```

2. Створіть віртуальне середовище:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# або
venv\Scripts\activate  # Windows
```

3. Встановіть залежності:
```bash
pip install -r requirements.txt
```

4. Створіть файл `.env` з налаштуваннями:
```
SECRET_KEY=your-secret-key
DEBUG=True
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

5. Виконайте міграції:
```bash
python manage.py migrate
```

6. Створіть суперкористувача:
```bash
python manage.py createsuperuser
```

7. Запустіть сервер:
```bash
python manage.py runserver
```

## Розгортання на Render

1. Створіть новий Web Service на Render
2. Підключіть GitHub репозиторій
3. Налаштуйте змінні середовища:
   - `SECRET_KEY`
   - `DEBUG=False`
   - `DATABASE_URL` (автоматично створюється Render)
4. Build Command: `./build.sh`
5. Start Command: `gunicorn cms_django.wsgi:application`

## Структура проєкту

```
django_cms/
├── cms_django/          # Основні налаштування Django
├── patients/            # Додаток для управління пацієнтами
├── templates/           # HTML шаблони
├── static/              # Статичні файли
├── manage.py           # Django management script
├── requirements.txt    # Python залежності
├── build.sh           # Скрипт для розгортання
└── README.md          # Цей файл
```

## Ліцензія

MIT License 