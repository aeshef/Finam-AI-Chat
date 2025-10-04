.PHONY: help build up down logs shell test lint format clean

# Цвета для вывода
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Показать это сообщение
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Finam x HSE Trade AI Hack - Baseline                     ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)Доступные команды:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

build: ## Собрать Docker образ
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Сборка Docker образа...                                  ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка .env файла...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(RED)✗ Файл .env не найден!$(NC)"; \
		echo "$(YELLOW)  Создаю из .env.example...$(NC)"; \
		cp .env.example .env; \
		echo "$(GREEN)✓ Файл .env создан. Не забудьте добавить API ключи!$(NC)"; \
	else \
		echo "$(GREEN)✓ Файл .env найден$(NC)"; \
	fi
	@echo ""
	@echo "$(YELLOW)➜ Проверка API ключей...$(NC)"
	@if ! grep -q "OPENROUTER_API_KEY=sk-" .env 2>/dev/null && ! grep -q "OPENROUTER_API_KEY=your" .env 2>/dev/null; then \
		echo "$(RED)⚠ OPENROUTER_API_KEY не установлен в .env!$(NC)"; \
		echo "$(YELLOW)  Получите ключ на https://openrouter.ai/$(NC)"; \
	else \
		echo "$(GREEN)✓ OPENROUTER_API_KEY настроен$(NC)"; \
	fi
	@echo ""
	@echo "$(YELLOW)➜ Запуск сборки Docker образа (это может занять несколько минут)...$(NC)"
	@docker compose build --progress=plain 2>&1 | grep -v "^#" || docker compose build
	@echo ""
	@echo "$(GREEN)✓ Сборка завершена!$(NC)"

up: ## Запустить приложение
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Запуск AI Ассистента Трейдера...                         ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка Docker образа...$(NC)"
	@if ! docker images | grep -q "finam-x-hse-trade-ai-hack-trader"; then \
		echo "$(YELLOW)  Образ не найден. Запускаю сборку...$(NC)"; \
		$(MAKE) build; \
	else \
		echo "$(GREEN)✓ Docker образ найден$(NC)"; \
	fi
	@echo ""
	@echo "$(YELLOW)➜ Запуск контейнеров...$(NC)"
	@docker compose up -d
	@echo ""
	@echo "$(GREEN)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(GREEN)║  ✓ Приложение успешно запущено!                           ║$(NC)"
	@echo "$(GREEN)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)🌐 Откройте в браузере:$(NC)"
	@echo "   $(GREEN)http://localhost:8501$(NC)"
	@echo ""
	@echo "$(YELLOW)📊 Полезные команды:$(NC)"
	@echo "   $(BLUE)make logs$(NC)       - Просмотр логов"
	@echo "   $(BLUE)make down$(NC)       - Остановить приложение"
	@echo "   $(BLUE)make restart$(NC)    - Перезапустить"
	@echo ""
	@sleep 2
	@echo "$(YELLOW)➜ Проверка здоровья контейнера (ждите ~30 сек)...$(NC)"
	@sleep 5
	@if docker compose ps | grep -q "Up"; then \
		echo "$(GREEN)✓ Контейнер работает$(NC)"; \
	else \
		echo "$(RED)✗ Проблема с запуском. Смотрите логи: make logs$(NC)"; \
	fi

down: ## Остановить приложение
	@echo "$(YELLOW)➜ Остановка приложения...$(NC)"
	@docker compose down
	@echo "$(GREEN)✓ Приложение остановлено$(NC)"

restart: down ## Перезапустить приложение
	@echo ""
	@$(MAKE) up

logs: ## Показать логи (Ctrl+C для выхода)
	@echo "$(YELLOW)➜ Логи приложения (Ctrl+C для выхода):$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════════════════$(NC)"
	@docker compose logs -f web

logs-tail: ## Показать последние 100 строк логов
	@echo "$(YELLOW)➜ Последние 100 строк логов:$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════════════════$(NC)"
	@docker compose logs --tail=100 web

shell: ## Открыть shell в контейнере
	@echo "$(YELLOW)➜ Открываю shell в контейнере...$(NC)"
	@docker compose exec web /bin/bash

ps: ## Показать статус контейнеров
	@echo "$(YELLOW)➜ Статус контейнеров:$(NC)"
	@docker compose ps

# ============================================================================
# Локальная разработка (без Docker)
# ============================================================================

install: ## Установить зависимости через Poetry
	@echo "$(YELLOW)➜ Установка зависимостей...$(NC)"
	@poetry install
	@echo "$(GREEN)✓ Зависимости установлены$(NC)"

dev-cli: ## Запустить CLI чат (локально)
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Запуск CLI чата...                                       ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@poetry run chat-cli

dev-web: ## Запустить Streamlit (локально)
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Запуск Streamlit веб-интерфейса...                       ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(GREEN)🌐 Откроется в браузере: http://localhost:8501$(NC)"
	@echo ""
	@poetry run streamlit run src/app/interfaces/chat_app.py

# ============================================================================
# Работа с submission
# ============================================================================

generate: ## Сгенерировать submission.csv
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Генерация submission.csv...                              ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@poetry run generate-submission

validate: ## Валидировать submission.csv
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Валидация submission.csv...                              ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@poetry run validate-submission

metrics: ## Подсчитать метрики
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Подсчет метрики accuracy...                              ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@poetry run calculate-metrics

# ============================================================================
# Качество кода
# ============================================================================

lint: ## Проверить код линтером
	@echo "$(YELLOW)➜ Проверка кода с Ruff...$(NC)"
	@poetry run ruff check .

format: ## Форматировать код
	@echo "$(YELLOW)➜ Форматирование кода...$(NC)"
	@poetry run ruff format .
	@echo "$(GREEN)✓ Код отформатирован$(NC)"

lint-fix: ## Исправить автофиксимые проблемы
	@echo "$(YELLOW)➜ Исправление проблем в коде...$(NC)"
	@poetry run ruff check --fix .
	@echo "$(GREEN)✓ Проблемы исправлены$(NC)"

# ============================================================================
# Очистка
# ============================================================================

clean: ## Очистить кэш и временные файлы
	@echo "$(YELLOW)➜ Очистка кэша...$(NC)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@rm -rf dist/ build/ *.egg-info
	@echo "$(GREEN)✓ Кэш очищен$(NC)"

clean-all: clean down ## Полная очистка (включая Docker)
	@echo "$(YELLOW)➜ Удаление Docker volumes...$(NC)"
	@docker compose rm -f
	@docker volume prune -f
	@echo "$(GREEN)✓ Полная очистка завершена$(NC)"

# ============================================================================
# Docker production команды
# ============================================================================

prod-build: ## Собрать production образ
	@echo "$(YELLOW)➜ Сборка production образа (без кэша)...$(NC)"
	@docker compose -f docker-compose.yml build --no-cache

prod-up: ## Запустить в production режиме
	@echo "$(YELLOW)➜ Запуск в production режиме...$(NC)"
	@docker compose -f docker-compose.yml up -d
	@echo "$(GREEN)✓ Production режим запущен$(NC)"

# ============================================================================
# Утилиты
# ============================================================================

env-example: ## Создать .env из .env.example
	@if [ -f .env ]; then \
		echo "$(RED)⚠ Файл .env уже существует!$(NC)"; \
		echo "$(YELLOW)  Переименуйте его или удалите перед созданием нового$(NC)"; \
	else \
		cp .env.example .env; \
		echo "$(GREEN)✓ Создан .env файл$(NC)"; \
		echo "$(YELLOW)⚠ Не забудьте заполнить API ключи!$(NC)"; \
	fi

check: ## Проверить готовность к работе
	@echo "$(BLUE)╔════════════════════════════════════════════════════════════╗$(NC)"
	@echo "$(BLUE)║  Проверка готовности к работе...                          ║$(NC)"
	@echo "$(BLUE)╚════════════════════════════════════════════════════════════╝$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка Python...$(NC)"
	@python3 --version && echo "$(GREEN)✓ Python установлен$(NC)" || echo "$(RED)✗ Python не найден$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка Poetry...$(NC)"
	@poetry --version && echo "$(GREEN)✓ Poetry установлен$(NC)" || echo "$(RED)✗ Poetry не найден$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка Docker...$(NC)"
	@docker --version && echo "$(GREEN)✓ Docker установлен$(NC)" || echo "$(RED)✗ Docker не найден$(NC)"
	@echo ""
	@echo "$(YELLOW)➜ Проверка .env файла...$(NC)"
	@if [ -f .env ]; then echo "$(GREEN)✓ .env файл существует$(NC)"; else echo "$(RED)✗ .env файл не найден$(NC)"; fi
	@echo ""
	@echo "$(YELLOW)➜ Проверка структуры проекта...$(NC)"
	@if [ -d src/app ]; then echo "$(GREEN)✓ src/app существует$(NC)"; else echo "$(RED)✗ src/app не найдена$(NC)"; fi
	@if [ -d scripts ]; then echo "$(GREEN)✓ scripts существует$(NC)"; else echo "$(RED)✗ scripts не найдена$(NC)"; fi
	@if [ -d data/processed ]; then echo "$(GREEN)✓ data/processed существует$(NC)"; else echo "$(RED)✗ data/processed не найдена$(NC)"; fi
	@echo ""
	@echo "$(GREEN)✓ Проверка завершена!$(NC)"
