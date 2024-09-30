# Используем официальный образ Python
FROM python:3.10.0-slim

# Устанавливаем зависимости
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем необходимые системные зависимости для Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Playwright и загружаем браузеры
RUN pip install playwright \
    && playwright install

# Копируем все файлы проекта в контейнер
COPY . /app

# Переходим в директорию приложения
WORKDIR /app

# Команда для запуска приложения
CMD ["python", "app.py"]