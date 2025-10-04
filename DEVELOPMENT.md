# Development Guide

## 🛠 Установка для разработки

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/Orange-Hack/finam-x-hse-trade-ai-hack-trader
cd finam-x-hse-trade-ai-hack-trader

# 2. Установите Poetry
curl -sSL https://install.python-poetry.org | python3 -

# 3. Установите зависимости
poetry install

# 4. Настройте окружение
cp .env.example .env
# Отредактируйте .env и добавьте API ключи
```

## 🏗 Архитектура

```
src/app/
├── adapters/       # Внешние интеграции (Finam API)
├── core/           # Основная логика (config, llm)
└── interfaces/     # UI (Streamlit, CLI)

scripts/
├── generate_submission.py  # Генерация submission
├── calculate_metrics.py    # Подсчет accuracy
└── validate_submission.py  # Валидация submission
```

## 📜 Основные скрипты

### generate_submission.py

Генерирует submission.csv используя LLM + few-shot learning.

```bash
poetry run generate-submission --num-examples 15
```

**Как улучшить accuracy:**
1. Экспериментируйте с количеством примеров (`--num-examples`)
2. Меняйте модель в `.env` (`OPENROUTER_MODEL=openai/gpt-4o`)
3. Улучшайте промпт в функции `create_prompt()`
4. Добавьте semantic similarity для выбора примеров
5. Реализуйте post-processing в `parse_llm_response()`

### calculate_metrics.py

Рассчитывает accuracy: `N_correct / N_total`

```bash
poetry run calculate-metrics --show-errors 10
```

### validate_submission.py

Проверяет структуру submission.csv.

```bash
poetry run validate-submission
```

## 🐳 Docker команды

```bash
# Запуск
make up             # docker-compose up -d

# Логи
make logs           # docker-compose logs -f

# Остановка
make down           # docker-compose down

# Перезапуск
make restart        # down + up

# Shell в контейнере
make shell          # docker-compose exec web /bin/bash
```

## ✅ Code Quality

```bash
make lint           # Проверить код
make format         # Форматировать код
make lint-fix       # Исправить проблемы
```

## 🎯 API Reference

### Finam API Client

```python
from src.app.adapters import FinamAPIClient

client = FinamAPIClient(access_token="your_token")

# Котировки
quote = client.get_quote("SBER@MISX")
orderbook = client.get_orderbook("SBER@MISX", depth=10)
candles = client.get_candles("SBER@MISX", timeframe="D")

# Счета и ордера
account = client.get_account("ACC-001-A")
orders = client.get_orders("ACC-001-A")
order = client.create_order("ACC-001-A", {...})
client.cancel_order("ACC-001-A", "ORD123")
```

### LLM

```python
from src.app.core import call_llm

messages = [{"role": "user", "content": "Hello"}]
response = call_llm(messages, temperature=0.3)
```

## 🚀 Идеи для улучшения

### Для accuracy (70% оценки):
- Улучшить промпт (больше деталей API)
- Semantic search для few-shot примеров
- Structured output (JSON mode)
- Разные модели (GPT-4o, Claude)
- Post-processing для исправления ошибок
- Retry логика при ошибках

### Для продвинутых кейсов (30% оценки):
- **Портфельный анализ**: визуализация (pie chart, sunburst), метрики, рекомендации
- **Рыночный сканер**: фильтрация по критериям, таблицы с sparklines
- **Бэктестинг**: симуляция стратегий, equity curve, метрики
- **Улучшенный UI**: кастомный дизайн, интерактивные графики
- **Real-time данные**: WebSocket подключение, живые обновления

## 🐛 Troubleshooting

**"ModuleNotFoundError: No module named 'src'"**
```bash
export PYTHONPATH=/path/to/project:$PYTHONPATH
# или
poetry run python scripts/...
```

**"OPENROUTER_API_KEY is not set"**
```bash
cp .env.example .env
# Заполните API ключи в .env
```

**Docker проблемы**
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up
```

## 📚 Полезные ссылки

- [Finam TradeAPI](https://tradeapi.finam.ru/)
- [OpenRouter](https://openrouter.ai/)
- [Streamlit Docs](https://docs.streamlit.io/)
