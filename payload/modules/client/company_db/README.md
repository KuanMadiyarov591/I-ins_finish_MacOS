# Company ER database (PostgreSQL)

По схеме [Kielx/Insurance-company-database](https://github.com/Kielx/Insurance-company-database)
и ER-диаграмме (region/city/street/client/employee/branch/phone/insurance/payment/claim).

## Getting Started

### 1. Поднять PostgreSQL

```powershell
docker compose up -d postgres
```

Проверка:

```powershell
docker compose ps postgres
# healthy + host port 5433 (container 5432)
```

### 2. Создать схему и демо-данные

```powershell
.\.venv\Scripts\python.exe -m pip install -q faker
$env:COMPANY_DATABASE_URL="postgresql+psycopg2://insura:insura@127.0.0.1:5433/insurance_company"
.\.venv\Scripts\python.exe scripts\seed_company_db.py --force
```

### 3. В админке InsuraDesk

Вкладка **СУБД** → обзор таблиц, клиенты, сотрудники, филиалы, полисы, убытки, платежи.

API:

- `GET /api/admin/company/health`
- `GET /api/admin/company/overview`
- `POST /api/admin/company/seed?force=true`
- `GET /api/admin/company/clients|employees|branches|insurances|claims|payments`

### Файлы

| Файл | Назначение |
|------|------------|
| `create.sql` | DDL PostgreSQL (15 таблиц) |
| `../scripts/seed_company_db.py` | генерация данных (Faker) |
| `../app/company_models.py` | ORM |
| `../app/api/company_admin_routes.py` | Admin API |

