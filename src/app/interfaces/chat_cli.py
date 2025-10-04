#!/usr/bin/env python3
"""
Интерактивный CLI чат с AI ассистентом трейдера

Использование:
    poetry run chat-cli
    python -m src.app.chat_cli
"""

import sys

import click
from pathlib import Path

from src.app.adapters import FinamAPIClient
from src.app.core import call_llm, get_settings
from src.app.orchestration.mapper import map_and_execute


def create_system_prompt() -> str:
    """Создать системный промпт для AI ассистента"""
    return """Ты - AI ассистент трейдера, работающий с Finam TradeAPI.

Твоя задача - помогать пользователю анализировать рынки и управлять портфелем.

Когда пользователь задает вопрос, ты должен:
1. Определить, какой API запрос нужен
2. Сформулировать запрос в формате: HTTP_METHOD /api/path
3. Я выполню этот запрос и верну результат
4. Ты должен проанализировать результат и дать понятный ответ пользователю

Доступные API endpoints:
- GET /v1/instruments/{symbol}/quotes/latest - текущая котировка
- GET /v1/instruments/{symbol}/orderbook - биржевой стакан
- GET /v1/instruments/{symbol}/bars - исторические свечи
- GET /v1/accounts/{account_id} - информация о счете и позициях
- GET /v1/accounts/{account_id}/orders - список ордеров
- POST /v1/accounts/{account_id}/orders - создание ордера
- DELETE /v1/accounts/{account_id}/orders/{order_id} - отмена ордера

Формат твоего ответа должен быть таким:
```
API_REQUEST: GET /v1/instruments/SBER@MISX/quotes/latest

<После получения ответа от API, проанализируй его и дай понятное объяснение>
```

Отвечай на русском языке, будь полезным и дружелюбным."""


def extract_api_request(text: str) -> tuple[str | None, str | None]:
    """Извлечь API запрос из ответа LLM"""
    if "API_REQUEST:" not in text:
        return None, None

    lines = text.split("\n")
    for line in lines:
        if line.strip().startswith("API_REQUEST:"):
            request = line.replace("API_REQUEST:", "").strip()
            parts = request.split(maxsplit=1)
            if len(parts) == 2:
                return parts[0], parts[1]
    return None, None


@click.command()
@click.option("--account-id", default=None, help="ID счета для работы (опционально)")
@click.option("--api-token", default=None, help="Finam API токен (или используйте FINAM_ACCESS_TOKEN)")
@click.option("--use-mapper", is_flag=True, default=False, help="Использовать единый NL→API маппер")
@click.option("--force-llm", is_flag=True, default=False, help="Принудительно использовать LLM в маппере")
@click.option("--train-file", default="data/processed/train.csv", help="Путь к train.csv для Known symbols")
def main(account_id: str | None, api_token: str | None, use_mapper: bool, force_llm: bool, train_file: str) -> None:  # noqa: C901
    """Запустить интерактивный CLI чат с AI ассистентом"""
    settings = get_settings()

    # Инициализируем клиент Finam API
    finam_client = FinamAPIClient(access_token=api_token)

    # Проверяем подключение
    if finam_client.access_token:
        click.echo("✅ Finam API токен установлен")
    else:
        click.echo("⚠️  Внимание: Finam API токен не установлен!")
        click.echo("   Установите переменную окружения FINAM_ACCESS_TOKEN")
        click.echo("   или используйте --api-token")

    click.echo("=" * 70)
    click.echo("🤖 AI Ассистент Трейдера (Finam TradeAPI)")
    click.echo("=" * 70)
    click.echo(f"Модель: {settings.openrouter_model}")
    click.echo(f"API URL: {finam_client.base_url}")
    if account_id:
        click.echo(f"Счет: {account_id}")
    click.echo("\nКоманды:")
    click.echo("  - Просто пишите свои вопросы на русском")
    click.echo("  - 'exit' или 'quit' - выход")
    click.echo("  - 'clear' - очистить историю")
    click.echo("=" * 70)

    conversation_history = [{"role": "system", "content": create_system_prompt()}]

    while True:
        try:
            # Получаем вопрос от пользователя
            user_input = click.prompt("\n👤 Вы", type=str, prompt_suffix=": ")

            if user_input.lower() in ["exit", "quit", "выход"]:
                click.echo("\n👋 До свидания!")
                break

            if user_input.lower() in ["clear", "очистить"]:
                conversation_history = [{"role": "system", "content": create_system_prompt()}]
                click.echo("🔄 История очищена")
                continue

            if use_mapper:
                settings = get_settings()
                mapped = map_and_execute(
                    question=user_input,
                    account_id=account_id,
                    model=settings.openrouter_model,
                    train_file=Path(train_file),
                    force_llm=force_llm,
                    api_token=api_token,
                )
                method = mapped.get("type", "GET")
                path = mapped.get("request", "/v1/assets")
                click.echo(f"\n   🔍 Выполняю запрос: {method} {path}")
                api_response = mapped.get("response", {})
                click.echo(f"   📡 Ответ API: {api_response}\n")

                # Просим LLM проанализировать
                conversation_history.append({"role": "user", "content": user_input})
                conversation_history.append({
                    "role": "user",
                    "content": f"Результат API запроса: {api_response}\n\nПроанализируй это.",
                })
                response = call_llm(conversation_history, temperature=0.3)
                assistant_message = response["choices"][0]["message"]["content"]
                click.echo(f"{assistant_message}\n")
                conversation_history.append({"role": "assistant", "content": assistant_message})
            else:
                # Старый режим: генерация API_REQUEST ассистентом
                conversation_history.append({"role": "user", "content": user_input})
                click.echo("🤖 Ассистент: ", nl=False)
                response = call_llm(conversation_history, temperature=0.3)
                assistant_message = response["choices"][0]["message"]["content"]
                method, path = extract_api_request(assistant_message)
                if method and path:
                    if account_id and "{account_id}" in path:  # noqa: RUF027
                        path = path.replace("{account_id}", account_id)
                    click.echo(f"\n   🔍 Выполняю запрос: {method} {path}")
                    api_response = finam_client.execute_request(method, path)
                    if "error" in api_response:
                        click.echo(f"   ⚠️  Ошибка API: {api_response.get('error')}", err=True)
                        if "details" in api_response:
                            click.echo(f"   Детали: {api_response['details']}", err=True)
                    else:
                        click.echo(f"   📡 Ответ API: {api_response}\n")
                    conversation_history.append({"role": "assistant", "content": assistant_message})
                    conversation_history.append({
                        "role": "user",
                        "content": f"Результат API запроса: {api_response}\n\nПроанализируй это.",
                    })
                    response = call_llm(conversation_history, temperature=0.3)
                    assistant_message = response["choices"][0]["message"]["content"]
                click.echo(f"{assistant_message}\n")
                conversation_history.append({"role": "assistant", "content": assistant_message})

        except KeyboardInterrupt:
            click.echo("\n\n👋 До свидания!")
            sys.exit(0)
        except Exception as e:
            click.echo(f"\n❌ Ошибка: {e}", err=True)


if __name__ == "__main__":
    main()
