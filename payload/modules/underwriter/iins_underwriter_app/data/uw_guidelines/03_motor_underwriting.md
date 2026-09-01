# Моторное страхование — underwriting guidelines

Линия **motor** (commercial / private motor portfolio).

## Ключевые факторы

- **has_claim = 1** — история убытка повышает скор.
- **CLAIM_PAID** относительно INSURED_VALUE — если выплата > 50% суммы на старом ТС, чаще decline/refer.
- **vehicle_age ≥ 15** — износ, запчасти, остаточная стоимость.
- **USAGE**: Taxi, Hire, General Cartage, Own Goods — коммерческий риск выше Private.
- **TYPE_VEHICLE**: Truck / Bus — выше exposure, чем Automobile / Motor-cycle.
- Высокое отношение PREMIUM / INSURED_VALUE — сигнал неверной тарификации или риска.

## Матрица решений (демо)

| Профиль | Типичное решение |
|---------|------------------|
| Private sedan, нет claim, age < 10 | Approve |
| Taxi / cartage, claim=1 | Refer |
| Truck, age ≥ 15, крупная выплата | Decline / refer senior |
| Motor-cycle, низкая сумма, нет claim | Approve с оговорками |

## Чеклист refer

1. Назначение использования (USAGE) и тип кузова.
2. Страховая сумма vs рыночная оценка.
3. История claim_paid за период полиса.
4. Возраст ТС и seats / ccm для коммерческих.

## Примечание Stage 1

Скоринг детерминированный по CSV-признакам; опциональная sklearn-модель лишь слегка корректирует скор, если файл модели обучен.
