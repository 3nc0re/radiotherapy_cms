# Запуск CMS проєкту в Docker

## Передумови

- Docker
- Docker Compose

## Швидкий запуск

1. **Клонуйте репозиторій та перейдіть в директорію проєкту:**
   ```bash
   cd django_cms
   ```

2. **Запустіть проєкт за допомогою Docker Compose:**
   ```bash
   docker-compose up --build
   ```

3. **Відкрийте браузер та перейдіть за адресою:**
   ```
   http://localhost:8000
   ```

## Створення суперкористувача

Після запуску контейнерів, створіть суперкористувача:

```bash
docker-compose exec web python manage.py createsuperuser
```

## Зупинка проєкту

```bash
docker-compose down
```

## Видалення всіх даних (включаючи базу даних)

```bash
docker-compose down -v
```

## Корисні команди

### Перегляд логів
```bash
docker-compose logs web
docker-compose logs db
```

### Запуск команд Django
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py collectstatic
docker-compose exec web python manage.py shell
```

### Доступ до бази даних
```bash
docker-compose exec db psql -U postgres -d cms_db
```

## Налаштування змінних середовища

Створіть файл `.env` в директорії `django_cms` з наступними змінними:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://postgres:postgres@db:5432/cms_db
```

## Структура контейнерів

- **web**: Django додаток (порт 8000)
- **db**: PostgreSQL база даних (порт 5432)

## Вирішення проблем

### Проблема з правами доступу
```bash
sudo chown -R $USER:$USER .
```

### Очищення Docker кешу
```bash
docker system prune -a
```

### Перезапуск сервісів
```bash
docker-compose restart web
docker-compose restart db
``` 