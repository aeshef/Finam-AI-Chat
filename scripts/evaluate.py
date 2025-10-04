#!/usr/bin/env python3
"""
Стандартный модуль оценки для хакатона

Интерфейс совместим с платформой автоматической проверки.
Оценка полностью основана на UID, порядок строк не важен.
"""

import csv
from pathlib import Path


def load_csv_data(file_path: str) -> dict[str, dict[str, str]]:
    """
    Загрузить CSV в словарь {uid: {type, request}}

    Порядок строк не важен, важен только UID
    """
    data = {}
    try:
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                uid = row.get("uid", "").strip()
                if uid:
                    data[uid] = {"type": row.get("type", "").strip(), "request": row.get("request", "").strip()}
    except Exception as e:
        raise ValueError(f"Failed to load CSV file: {e}") from e
    return data


def validate_submission(  # noqa: C901
    submission: dict[str, dict], required_uids: set[str]
) -> tuple[bool, list[str]]:
    """
    СТРОГАЯ валидация submission перед подсчетом метрик

    Критерии валидности:
    1. Наличие ВСЕХ required UID (из public + private)
    2. Все поля заполнены (type и request)
    3. HTTP методы валидны
    4. API пути начинаются с /

    Args:
        submission: Словарь предсказаний {uid: {type, request}}
        required_uids: Множество обязательных UID

    Returns:
        (is_valid, errors): True если все проверки прошли, иначе False со списком ошибок
    """
    errors: list[str] = []
    valid_http_methods = {"GET", "POST", "DELETE", "PUT", "PATCH", "HEAD", "OPTIONS"}

    # 1. Проверка наличия ВСЕХ required UID
    submission_uids = set(submission.keys())
    missing_uids = required_uids - submission_uids
    extra_uids = submission_uids - required_uids

    if missing_uids:
        errors.append(f"Missing {len(missing_uids)} required UIDs")
        # НЕ показываем конкретные UID для избежания утечки данных

    if extra_uids:
        errors.append(f"Found {len(extra_uids)} extra UIDs not in test set")

    # 2-4. Проверка каждой записи
    empty_type_count = 0
    empty_request_count = 0
    invalid_method_count = 0
    invalid_path_count = 0

    for uid in required_uids:
        if uid not in submission:
            continue  # Уже учтено в missing_uids

        data = submission[uid]
        method = data.get("type", "")
        request = data.get("request", "")

        # Проверка пустых полей
        if not method:
            empty_type_count += 1
        if not request:
            empty_request_count += 1

        # Проверка валидности HTTP метода
        if method and method not in valid_http_methods:
            invalid_method_count += 1

        # Проверка формата API пути
        if request and not request.startswith("/"):
            invalid_path_count += 1

    if empty_type_count > 0:
        errors.append(f"Empty 'type' field in {empty_type_count} predictions")

    if empty_request_count > 0:
        errors.append(f"Empty 'request' field in {empty_request_count} predictions")

    if invalid_method_count > 0:
        errors.append(f"Invalid HTTP method in {invalid_method_count} predictions (must be GET/POST/DELETE/etc)")

    if invalid_path_count > 0:
        errors.append(f"Invalid API path in {invalid_path_count} predictions (must start with /)")

    # Submission валиден только если нет ошибок
    is_valid = len(errors) == 0

    return is_valid, errors


def calculate_accuracy(submission: dict[str, dict], ground_truth: dict[str, dict]) -> tuple[float, dict]:
    """
    Рассчитать accuracy метрику (только для валидных submission)

    Сравнение строго по UID, порядок строк не важен

    Returns:
        tuple: (accuracy_score, detailed_metrics)
    """
    if not ground_truth:
        return 0.0, {"error": "Ground truth is empty"}

    total = len(ground_truth)
    correct = 0
    correct_type = 0
    correct_request = 0

    for uid, true_data in ground_truth.items():
        # Проверяем наличие UID в submission
        if uid not in submission:
            continue  # Не должно случиться после валидации

        pred_data = submission[uid]

        # Извлекаем значения
        true_type = true_data.get("type", "")
        pred_type = pred_data.get("type", "")
        true_request = true_data.get("request", "")
        pred_request = pred_data.get("request", "")

        # Точное совпадение строк
        type_match = true_type == pred_type
        request_match = true_request == pred_request

        if type_match:
            correct_type += 1
        if request_match:
            correct_request += 1
        if type_match and request_match:
            correct += 1

    # Считаем проценты
    accuracy = (correct / total * 100.0) if total > 0 else 0.0
    type_accuracy = (correct_type / total * 100.0) if total > 0 else 0.0
    request_accuracy = (correct_request / total * 100.0) if total > 0 else 0.0

    metrics = {
        "total_samples": total,
        "correct_predictions": correct,
        "type_accuracy": round(type_accuracy, 2),
        "request_accuracy": round(request_accuracy, 2),
    }

    return accuracy, metrics


def evaluate(submission_path: str, private_test_path: str, public_test_path: str) -> dict:  # noqa: C901
    """
    Standard evaluation interface with public/private leaderboard split.

    ПРОЦЕСС ОЦЕНКИ:
    1. Загрузка всех файлов
    2. СТРОГАЯ валидация submission (наличие всех UID, заполненность полей)
    3. Если валидация провалена - возврат score=0.0 с ошибками
    4. Если валидация прошла - подсчет accuracy отдельно для public и private

    Args:
        submission_path: Path to team's submission file
        private_test_path: Path to private test dataset (used for final ranking)
        public_test_path: Path to public test dataset (visible leaderboard during competition)

    Returns:
        {
            "public_score": float,   # Score on public data (0.0 - 100.0), shown to teams
            "private_score": float,  # Score on private data (0.0 - 100.0), hidden until end
            "metrics": dict,         # Additional metrics
            "errors": list[str],     # Error messages WITHOUT revealing data details
        }

    Important:
        - public_score is shown on leaderboard during competition
        - private_score is used for final ranking after competition ends
        - errors should contain only general messages without data leakage
        - For critical errors, return scores = 0.0 with error description
        - Evaluation is strictly UID-based, row order doesn't matter
    """

    # ШАГ 1: Проверка существования файлов
    if not Path(submission_path).exists():
        return {
            "public_score": 0.0,
            "private_score": 0.0,
            "metrics": {},
            "errors": ["Submission file not found"],
        }

    if not Path(public_test_path).exists():
        return {
            "public_score": 0.0,
            "private_score": 0.0,
            "metrics": {},
            "errors": ["Public test file not found (internal error)"],
        }

    if not Path(private_test_path).exists():
        return {
            "public_score": 0.0,
            "private_score": 0.0,
            "metrics": {},
            "errors": ["Private test file not found (internal error)"],
        }

    try:
        # ШАГ 2: Загрузка данных
        try:
            submission = load_csv_data(submission_path)
        except Exception as e:
            return {
                "public_score": 0.0,
                "private_score": 0.0,
                "metrics": {},
                "errors": [f"Failed to parse submission file: {e!s}"],
            }

        if not submission:
            return {
                "public_score": 0.0,
                "private_score": 0.0,
                "metrics": {},
                "errors": ["Submission file is empty"],
            }

        try:
            public_test = load_csv_data(public_test_path)
        except Exception as e:
            return {
                "public_score": 0.0,
                "private_score": 0.0,
                "metrics": {},
                "errors": [f"Failed to load public test (internal error): {e!s}"],
            }

        try:
            private_test = load_csv_data(private_test_path)
        except Exception as e:
            return {
                "public_score": 0.0,
                "private_score": 0.0,
                "metrics": {},
                "errors": [f"Failed to load private test (internal error): {e!s}"],
            }

        # ШАГ 3: СТРОГАЯ ВАЛИДАЦИЯ submission
        # Submission должен содержать ВСЕ UID из public + private
        required_uids = set(public_test.keys()) | set(private_test.keys())

        is_valid, validation_errors = validate_submission(submission, required_uids)

        if not is_valid:
            # Валидация провалена - возвращаем 0.0 баллов
            return {
                "public_score": 0.0,
                "private_score": 0.0,
                "metrics": {
                    "validation_failed": True,
                    "submission_size": len(submission),
                    "required_size": len(required_uids),
                },
                "errors": validation_errors,
            }

        # ШАГ 4: Подсчет accuracy (только для валидных submission)
        public_score = 0.0
        public_metrics: dict = {}
        if public_test:
            public_score, public_metrics = calculate_accuracy(submission, public_test)

        private_score = 0.0
        private_metrics: dict = {}
        if private_test:
            private_score, private_metrics = calculate_accuracy(submission, private_test)

        # Финальные метрики
        combined_metrics = {
            "public_metrics": public_metrics,
            "private_metrics": private_metrics,
            "submission_size": len(submission),
            "validation_passed": True,
        }

        return {
            "public_score": round(public_score, 2),
            "private_score": round(private_score, 2),
            "metrics": combined_metrics,
            "errors": [],  # Нет ошибок для валидных submission
        }

    except Exception as e:
        # Непредвиденная ошибка
        return {
            "public_score": 0.0,
            "private_score": 0.0,
            "metrics": {},
            "errors": [f"Unexpected error during evaluation: {e!s}"],
        }


if __name__ == "__main__":
    # Пример использования
    import sys

    if len(sys.argv) != 4:
        print("Usage: python evaluate.py <submission.csv> <private.csv> <public.csv>")
        print()
        print("Example:")
        print("  python evaluate.py data/processed/submission.csv data/interim/private.csv data/interim/public.csv")
        sys.exit(1)

    result = evaluate(sys.argv[1], sys.argv[2], sys.argv[3])

    print("=" * 70)
    print("EVALUATION RESULTS")
    print("=" * 70)
    print(f"Public Score:  {result['public_score']:.2f}%")
    print(f"Private Score: {result['private_score']:.2f}%")
    print()

    if result["metrics"]:
        print("Metrics:")
        for key, value in result["metrics"].items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")
        print()

    if result["errors"]:
        print("⚠️  ERRORS:")
        for error in result["errors"]:
            print(f"  - {error}")
        print()
        print("NOTE: Scores are 0.0 due to validation errors.")
    else:
        print("✅ No errors - submission is valid!")

    print("=" * 70)
