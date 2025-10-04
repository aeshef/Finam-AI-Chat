# \[Trader\] Finam x HSE Trade AI Hack - Baseline

> **AI-ассистент трейдера** на базе Finam TradeAPI
> Базовый шаблон для хакатона по созданию интеллектуального помощника для трейдинга

## 🚀 Быстрый старт

### Быстрая оффлайн‑проверка (репозиторий)

Для сабмита в формате репозитория (без Docker) доступны оффлайн‑скрипты:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Сгенерировать submission (объединить public train + public test)
python scripts/generate_submission_offline.py \
  --test-file data/processed/test.csv \
  --include-train data/processed/train.csv \
  --output-file data/processed/submission.csv

# Оценить локально (совместимо с форматом хакатона)
python scripts/evaluate.py data/processed/submission.csv data/processed/test.csv data/processed/train.csv
```

Скрипт проверяет покрытие UID и выводит public/private score. API ключи не требуются.

### One‑liner для генерации сабмишна (форс LLM)

```bash
cd "/Users/aeshef/Desktop/FINAM/finam-x-hse-trade-ai-hack-trader-main" && \
source .venv/bin/activate && \
export OPENROUTER_API_KEY='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' && \
python scripts/generate_submission.py \
  --test-file data/processed/test.csv \
  --train-file data/processed/train.csv \
  --output-file data/processed/submission.csv \
  --num-examples 100 \
  --force-llm && \
python scripts/merge_predictions.py data/processed/test.csv data/processed/submission.csv data/processed/test_diagnostics.csv
```

Замена модели (опц.): `export OPENROUTER_MODEL="openai/gpt-4o"` (по умолчанию уже gpt‑4o).

### Вариант 1: Docker (рекомендуется)

```bash
# 1. Скопируйте пример конфигурации
cp .env.example .env

# 2. Отредактируйте .env и добавьте API ключи
# OPENROUTER_API_KEY=your_key
# FINAM_ACCESS_TOKEN=your_token (опционально)

# 3. Запустите приложение
make up
# или: docker-compose up -d

# 4. Откройте в браузере
# http://localhost:8501
```

### Вариант 2: Локально

```bash
# 1. Установите зависимости
poetry install

# 2. Настройте .env
cp .env.example .env

# 3. Запустите веб-интерфейс
poetry run streamlit run src/app/interfaces/chat_app.py

# ИЛИ CLI чат
poetry run chat-cli
```

## 📋 Основные команды

```bash
# Генерация submission.csv
make generate
# или: poetry run generate-submission

# Валидация submission
make validate
# или: poetry run validate-submission

# Подсчет метрики
make metrics
# или: poetry run calculate-metrics

# Просмотр логов Docker
make logs
```

## 🎯 Задача

Создать AI-ассистента, который преобразует вопросы на естественном языке в HTTP запросы к Finam TradeAPI.

**Пример:**
- Вопрос: *"Какая цена Сбербанка?"*
- API запрос: `GET /v1/instruments/SBER@MISX/quotes/latest`

**Метрика:**
```
Accuracy = N_correct / N_total
```

Запрос считается правильным, если полностью совпал с эталоном (и HTTP метод, и путь).

## 📁 Структура проекта

```
├── src/app/
│   ├── adapters/          # Finam API клиент
│   ├── core/              # Основная логика (LLM, config)
│   └── interfaces/        # UI (Streamlit, CLI)
├── scripts/               # Утилиты
│   ├── generate_submission.py
│   ├── validate_submission.py
│   └── calculate_metrics.py
├── data/processed/
│   ├── train.csv         # 100 обучающих примеров
│   ├── test.csv          # 300 тестовых вопросов
│   └── submission.csv    # Ваши предсказания
└── docs/                 # Документация хакатона
```

Короткая разбивка по модулям

- src/app/orchestration: планирование → экстракция → safety → исполнение через `ToolRouter`
- src/app/registry: `EndpointRegistry` (SSOT), классификация путей, подсказки политик
- src/app/leaderboard/offline_map.py: детерминированный NL→API маппер без LLM
- src/app/core: конфигурация (`config.py`), вызовы LLM, нормализации, политика, метрики
- src/app/interfaces: `chat_app.py` (Streamlit UI), `chat_cli.py`
- src/app/backtest, scanner, portfolio, alerts: функциональные блоки (бэктест, сканер, портфель, алерты)
- scripts: `generate_submission.py` (LLM), `generate_submission_offline.py` (оффлайн), `evaluate.py`

## 🔑 Необходимые API ключи

1. **OpenRouter API** (обязательно)
   - Регистрация: https://openrouter.ai/
   - Используется для LLM (GPT-4o-mini, GPT-4o, Claude и др.)

2. **Finam TradeAPI** (опционально для чата)
   - Документация: https://tradeapi.finam.ru/
   - Нужен только для работы с реальным API в чат-интерфейсе

## 💡 Что дальше?

### Для участников хакатона:
1. **Улучшите accuracy** - экспериментируйте с промптами, few-shot примерами, моделями
2. **Реализуйте продвинутые кейсы** - портфельный анализ, визуализация, бэктестинг
3. **Создайте UI** - используйте готовый Streamlit или создайте свой

### Полезные ссылки:
- [DEVELOPMENT.md](DEVELOPMENT.md) - подробная информация для разработки
- [SUMMARY.md](SUMMARY.md) - итоговое резюме проекта
- [docs/task.md](docs/task.md) - полное описание задачи
- [docs/evaluation.md](docs/evaluation.md) - методология оценки

## 📊 Пример работы

**Генерация submission:**
```bash
poetry run generate-submission --num-examples 15

🚀 Генерация submission файла...
✅ Загружено 15 примеров для few-shot learning
🤖 Используется модель: openai/gpt-4o-mini

Обработка: 100%|████████| 300/300 [02:15, cost=$0.0423]

💰 Общая стоимость: $0.0423
📊 GET: 285, POST: 12, DELETE: 3
```

**Подсчет метрики:**
```bash
poetry run calculate-metrics

🎯 ОСНОВНАЯ МЕТРИКА:
   Accuracy = 87/100 = 0.8700 (87.00%)
```

## 🤝 Поддержка

Для вопросов по хакатону обращайтесь к организаторам.

## 📄 Лицензия

Этот проект создан как baseline для хакатона Finam x HSE.
