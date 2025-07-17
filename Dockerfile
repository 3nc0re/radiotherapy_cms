# Використовуємо офіційний Python образ
FROM python:3.11-slim

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо файли залежностей
COPY requirements.txt .

# Встановлюємо Python залежності
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо код проєкту
COPY . .

# Створюємо директорію для статичних файлів
RUN mkdir -p staticfiles

# Збираємо статичні файли
RUN python manage.py collectstatic --noinput

# Відкриваємо порт
EXPOSE 8000

# Створюємо скрипт для запуску
RUN echo '#!/bin/bash\n\
python manage.py migrate\n\
python manage.py collectstatic --noinput\n\
gunicorn cms_django.wsgi:application --bind 0.0.0.0:8000 --workers 3' > /app/start.sh

RUN chmod +x /app/start.sh

# Запускаємо додаток
CMD ["/app/start.sh"] 