# Тестування CMS проєкту в Docker

## Швидкий запуск для тестування

1. **Перейдіть в директорію проєкту:**
   ```bash
   cd django_cms
   ```

2. **Запустіть тестовий контейнер:**
   ```bash
   docker-compose -f docker-compose.test.yml up --build
   ```

3. **Відкрийте браузер:**
   ```
   http://localhost:8000
   ```

## Особливості тестового контейнера

- ✅ **SQLite база даних** - вбудована, не потребує окремого сервісу
- ✅ **Мінімальні залежності** - тільки Django та python-dotenv
- ✅ **Швидка збірка** - без PostgreSQL та інших важких пакетів
- ✅ **Гаряче перезавантаження** - зміни в коді відображаються автоматично

## Корисні команди для тестування

### Запуск тестів Django
```bash
docker-compose -f docker-compose.test.yml exec web python manage.py test
```

### Створення суперкористувача
```bash
docker-compose -f docker-compose.test.yml exec web python manage.py createsuperuser
```

### Запуск міграцій
```bash
docker-compose -f docker-compose.test.yml exec web python manage.py migrate
```

### Доступ до Django shell
```bash
docker-compose -f docker-compose.test.yml exec web python manage.py shell
```

### Перегляд логів
```bash
docker-compose -f docker-compose.test.yml logs web
```

## Зупинка тестового контейнера

```bash
docker-compose -f docker-compose.test.yml down
```

## Очищення тестових даних

```bash
docker-compose -f docker-compose.test.yml down -v
docker system prune -f
```

## Структура тестового контейнера

- **web**: Django додаток з SQLite (порт 8000)
- **База даних**: SQLite файл в контейнері
- **Volumes**: Монтування коду для гарячого перезавантаження

## Переваги для тестування

1. **Швидкий старт** - немає потреби в PostgreSQL
2. **Легка конфігурація** - мінімум налаштувань
3. **Ізольоване середовище** - не впливає на локальну систему
4. **Портативність** - працює на будь-якій системі з Docker 