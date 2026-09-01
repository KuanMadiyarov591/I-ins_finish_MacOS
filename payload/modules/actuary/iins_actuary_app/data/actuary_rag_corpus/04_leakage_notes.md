# Leakage и честная валидация

## Что такое leakage

Data leakage — когда модель видит информацию, недоступную в момент решения или напрямую содержащую ответ. Для премий типичный пример: `current_premium` почти повторяет `selected_premium`.

## Правило Actuary Desk

**EXCLUDE `current_premium` из признаков.** Даже если MAE «красивый» с этим полем — метрика обманчива.

## Допустимые признаки Stage 1

`ypc`, `fixed_expenses`, `age`, `indicated_premium`, `territory`, `gender`, `cgr`.

## Метрики

Смотрите MAE и R² в `models/actuary/metrics.json` и на вкладке **Прогоны**. Обучайте на сэмпле ≤ ~40k строк (HistGradientBoostingRegressor или лучший доступный sklearn).

## Чеклист перед демо

1. Модель обучена без current_premium.
2. Smoke-тест проходит.
3. Рекомендации показывают predicted, indicated, gap и factors.
