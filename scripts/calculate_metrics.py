#!/usr/bin/env python3
"""
Скрипт для подсчета метрики accuracy для submission файла.

Метрика из evaluation.md:
    Accuracy = N_пройденных_запросов / N_всего_запросов

Запрос считается пройденным, если сгенерированный вызов API
полностью совпал с эталонным (и type, и request).

Использование:
    python scripts/calculate_metrics.py --pred submission.csv --true train.csv
    python scripts/calculate_metrics.py  # использует значения по умолчанию

Примеры:
    # Подсчет метрики для submission.csv
    poetry run calculate-metrics

    # Подсчет для конкретных файлов
    poetry run calculate-metrics --pred data/processed/submission.csv --true data/processed/train.csv

    # С отображением ошибок
    poetry run calculate-metrics --show-errors 5
"""

import csv
from pathlib import Path
from typing import Optional

import click


def load_csv(file_path: Path) -> dict[str, dict[str, str]]:
    """Загрузить CSV файл в словарь {uid: {type, request}}"""
    data = {}
    with open(file_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            uid = row["uid"]
            data[uid] = {"type": row["type"], "request": row["request"]}
    return data


def calculate_accuracy(
    predicted: dict[str, dict[str, str]], ground_truth: dict[str, dict[str, str]]
) -> tuple[float, dict]:
    """
    Рассчитать accuracy и детальную статистику

    Returns:
        tuple: (accuracy, detailed_stats)
    """
    total = len(ground_truth)
    correct = 0
    correct_type = 0
    correct_request = 0

    errors = []
    type_stats = {
        "GET": {"tp": 0, "fp": 0, "fn": 0},
        "POST": {"tp": 0, "fp": 0, "fn": 0},
        "DELETE": {"tp": 0, "fp": 0, "fn": 0},
    }

    for uid, true_data in ground_truth.items():
        if uid not in predicted:
            errors.append({
                "uid": uid,
                "error": "missing",
                "true_type": true_data["type"],
                "true_request": true_data["request"],
                "pred_type": None,
                "pred_request": None,
            })
            type_stats[true_data["type"]]["fn"] += 1
            continue

        pred_data = predicted[uid]
        true_type = true_data["type"]
        pred_type = pred_data["type"]
        true_request = true_data["request"]
        pred_request = pred_data["request"]

        type_match = true_type == pred_type
        request_match = true_request == pred_request

        if type_match:
            correct_type += 1

        if request_match:
            correct_request += 1

        if type_match and request_match:
            correct += 1
            type_stats[true_type]["tp"] += 1
        else:
            errors.append({
                "uid": uid,
                "error": "mismatch",
                "true_type": true_type,
                "true_request": true_request,
                "pred_type": pred_type,
                "pred_request": pred_request,
                "type_match": "yes" if type_match else "no",
                "request_match": "yes" if request_match else "no",
            })
            if not type_match:
                type_stats[true_type]["fn"] += 1
                if pred_type in type_stats:
                    type_stats[pred_type]["fp"] += 1

    accuracy = correct / total if total > 0 else 0.0
    type_accuracy = correct_type / total if total > 0 else 0.0
    request_accuracy = correct_request / total if total > 0 else 0.0

    # Рассчитываем precision, recall, f1 для каждого типа
    detailed_type_stats = {}
    for method, stats in type_stats.items():
        tp = stats["tp"]
        fp = stats["fp"]
        fn = stats["fn"]

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        detailed_type_stats[method] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    return accuracy, {
        "total": total,
        "correct": correct,
        "correct_type": correct_type,
        "correct_request": correct_request,
        "type_accuracy": type_accuracy,
        "request_accuracy": request_accuracy,
        "errors": errors,
        "type_stats": detailed_type_stats,
    }


@click.command()
@click.option(
    "--pred",
    "pred_file",
    type=click.Path(exists=True, path_type=Path),
    default="data/processed/submission.csv",
    help="Путь к predicted файлу (submission.csv)",
)
@click.option(
    "--true",
    "true_file",
    type=click.Path(exists=True, path_type=Path),
    default="data/processed/train.csv",
    help="Путь к ground truth файлу",
)
@click.option(
    "--show-errors",
    type=int,
    default=0,
    help="Количество примеров ошибок для отображения (0 = не показывать)",
)
@click.option(
    "--save-errors",
    type=click.Path(path_type=Path),
    default=None,
    help="Сохранить все ошибки в CSV файл",
)
def main(pred_file: Path, true_file: Path, show_errors: int, save_errors: Optional[Path]) -> None:  # noqa: C901
    """Рассчитать метрику accuracy для submission файла"""

    click.echo("📊 Расчет метрики accuracy...")
    click.echo(f"📖 Predicted: {pred_file}")
    click.echo(f"📖 Ground Truth: {true_file}")
    click.echo("=" * 70)

    # Загружаем данные
    try:
        predicted = load_csv(pred_file)
        ground_truth = load_csv(true_file)
    except Exception as e:
        click.echo(f"❌ Ошибка при чтении файлов: {e}", err=True)
        return

    # Рассчитываем метрики
    accuracy, stats = calculate_accuracy(predicted, ground_truth)

    # Выводим результаты
    click.echo("\n🎯 ОСНОВНАЯ МЕТРИКА (из evaluation.md):")
    click.echo(f"   Accuracy = {stats['correct']}/{stats['total']} = {accuracy:.4f} ({accuracy * 100:.2f}%)")

    click.echo("\n📈 ДЕТАЛЬНАЯ СТАТИСТИКА:")
    click.echo(f"   Всего запросов:           {stats['total']}")
    click.echo(f"   Полностью правильных:     {stats['correct']} ({accuracy * 100:.2f}%)")
    click.echo(f"   Правильный type:          {stats['correct_type']} ({stats['type_accuracy'] * 100:.2f}%)")
    click.echo(f"   Правильный request:       {stats['correct_request']} ({stats['request_accuracy'] * 100:.2f}%)")
    click.echo(f"   Ошибок:                   {len(stats['errors'])}")

    # Статистика по типам запросов
    click.echo("\n📊 СТАТИСТИКА ПО ТИПАМ ЗАПРОСОВ:")
    click.echo(f"   {'Type':<10} {'Precision':<12} {'Recall':<12} {'F1-Score':<12}")
    click.echo(f"   {'-' * 46}")
    for method, method_stats in sorted(stats["type_stats"].items()):
        click.echo(
            f"   {method:<10} "
            f"{method_stats['precision']:.4f} ({method_stats['precision'] * 100:>5.1f}%)  "
            f"{method_stats['recall']:.4f} ({method_stats['recall'] * 100:>5.1f}%)  "
            f"{method_stats['f1']:.4f} ({method_stats['f1'] * 100:>5.1f}%)"
        )

    # Показываем примеры ошибок
    if show_errors > 0 and stats["errors"]:
        click.echo(f"\n❌ ПРИМЕРЫ ОШИБОК (первые {show_errors}):")
        click.echo("=" * 70)
        for i, error in enumerate(stats["errors"][:show_errors], 1):
            click.echo(f"\n   Ошибка #{i} (uid: {error['uid']}):")
            if error["error"] == "missing":
                click.echo("   ⚠️  Отсутствует в predicted файле")
                click.echo(f"   Expected: {error['true_type']} {error['true_request']}")
            else:
                if error["type_match"] == "no":
                    click.echo(f"   Type:    ✗ {error['pred_type']} (ожидалось: {error['true_type']})")
                else:
                    click.echo(f"   Type:    ✓ {error['true_type']}")

                if error["request_match"] == "no":
                    click.echo("   Request: ✗")
                    click.echo(f"     Predicted: {error['pred_request']}")
                    click.echo(f"     Expected:  {error['true_request']}")
                else:
                    click.echo(f"   Request: ✓ {error['true_request']}")

    # Сохраняем ошибки в файл
    if save_errors and stats["errors"]:
        save_errors = Path(save_errors)
        save_errors.parent.mkdir(parents=True, exist_ok=True)

        with open(save_errors, "w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "uid",
                "error_type",
                "true_type",
                "pred_type",
                "true_request",
                "pred_request",
                "type_match",
                "request_match",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
            writer.writeheader()

            for error in stats["errors"]:
                writer.writerow({
                    "uid": error["uid"],
                    "error_type": error["error"],
                    "true_type": error.get("true_type", ""),
                    "pred_type": error.get("pred_type", ""),
                    "true_request": error.get("true_request", ""),
                    "pred_request": error.get("pred_request", ""),
                    "type_match": error.get("type_match", ""),
                    "request_match": error.get("request_match", ""),
                })

        click.echo(f"\n💾 Ошибки сохранены в: {save_errors}")

    # Финальный вердикт
    click.echo("\n" + "=" * 70)
    if accuracy == 1.0:
        click.echo("🎉 ИДЕАЛЬНО! Все запросы совпали с эталоном!")
    elif accuracy >= 0.9:
        click.echo("🌟 ОТЛИЧНО! Очень высокая точность!")
    elif accuracy >= 0.7:
        click.echo("👍 ХОРОШО! Приличная точность, но есть куда расти.")
    elif accuracy >= 0.5:
        click.echo("😐 СРЕДНЕ. Нужно улучшать промпт и few-shot примеры.")
    else:
        click.echo("😞 ПЛОХО. Требуется серьезная доработка.")


if __name__ == "__main__":
    main()
