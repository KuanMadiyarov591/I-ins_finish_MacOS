# Fraud signals — сигналы мошенничества по убыткам

Playbook для линии **fraud** (claims fraud review). Идеи из underwriting playbooks; без внешних систем.

## Сильные сигналы

- **fraud_reported = 1** в исходных данных — высокий приоритет расследования.
- **Major / Total damage** без police report или с `police_report_available = ?/NO`.
- **0 witnesses** при серьёзном инциденте.
- Короткий срок клиента (**months_as_customer < 12**).
- Высокий **umbrella_limit** при низкой премии.

## Умеренные сигналы

- Property damage = YES при отсутствии отчёта полиции.
- Multi-vehicle (≥ 3) + bodily injuries ≥ 2.
- Incident type = Vehicle Theft без подтверждающих деталей.
- Несогласованность штата полиса и места инцидента (если видно в данных).

## Процесс refer

1. Зафиксировать список reasons из скорера.
2. Запросить police report / photos / repair estimate.
3. Сверить insured hobbies / occupation только как контекст, не как единственный фактор.
4. При подтверждённом fraud — **decline** и эскалация SIU (демо-заметка в notes).

## Что не делать

- Не отклонять только по occupation/hobbies.
- Не игнорировать отсутствие fraud_reported — правила всё равно считают severity и witnesses.
