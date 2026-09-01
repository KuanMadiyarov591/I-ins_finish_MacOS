# Продление полисов — renewal underwriting playbook



Playbook для андеррайтера по **продлению** (renewals). Интерфейс Underwriter Desk / Insura UW.



## Цели процесса продления



1. Снизить lapse (отток) по прибыльному портфелю.

2. Выявить do-not-renew и high-risk до даты renewal.

3. Ускорить решение: Approve / Refer / Decline с прозрачными reasons.

4. Согласовать премию и условия с риск-скором и рекомендацией AI.



## Action Items (дашборд)



| KPI | Что значит | Типичное действие |

|-----|------------|-------------------|

| Up for renewal | Открытые кейсы new / in_review | Взять в анализ, проверить loss signals |

| About to lapse | Продление ≤ 14 дней | Приоритет очереди, звонок / запрос документов |

| Open opportunities | New + Refer | Upsell / коррекция тарифа при approve |

| Payment due | Fraud signal / высокий риск без решения | Не продлевать без SIU / refer |



## Chevron stages (стадии кейса)



1. **Not Analyzed** (`new`) — кейс загружен, скорер уже поставил score, решение UW не начато.

2. **In Analysis** (`in_review`) — андеррайтер работает: сверяет признаки, документы.

3. **Refer / Escalate** (`referred`) — нужны доп. данные, SIU или senior UW.

4. **Approved** (`approved`) — продление / принятие риска.

5. **Declined / Closed** (`declined`) — do-not-renew или отказ.



## Когда Approve при продлении



- Риск-скор 0–44, нет fraud_signal.

- Нет свежих Major damage / claim без отчёта.

- Премия согласована с exposure (USAGE, возраст ТС, история).

- Клиент «книги» (retained book) — приоритет удержания при умеренном риске.



## Когда Refer



- Скор 45–74 или комбинация умеренных флагов (DUI=1, 1–2 accidents, Taxi usage).

- Нет police report при серьёзном инциденте.

- Расхождение PREMIUM / INSURED_VALUE.

- Короткий tenure + высокий umbrella.



## Когда Decline / Do-not-renew



- Скор ≥ 75 или hard decline rules (повторный DUI, confirmed fraud, крупная выплата на старом ТС).

- Повторные fraud signals без объяснения.

- Коммерческий truck/bus + claim_paid > 50% суммы + возраст ≥ 12.



## Чеклист UW на карточке полиса



1. Сверить **policy number**, insured, line, premium, renewal date.

2. Прочитать **AI recommendation** и список reasons / risk factors.

3. Оценить loss-like сигналы из CSV (DUI, accidents, fraud_reported, has_claim).

4. Выбрать решение Approve / Refer / Decline и зафиксировать notes.

5. Для Refer — перечень документов (ВУ, police report, photos, usage confirmation).



## Связь с RAG-консультантом



Спрашивайте консультанта: «когда refer при DUI», «чеклист taxi renewal», «сигналы fraud без police report».

Режим **auto** выбирает Ollama/Qwen если доступна, иначе extractive TF-IDF по корпусу guidelines.

