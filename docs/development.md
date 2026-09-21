# Разработка и релизы

[Документация](README.md) · [Архитектура](HLD.md)

## Локальная разработка

Из корня проекта запусти backend:

```bash
python run.py --reload
```

В другом терминале запусти frontend:

```bash
cd frontend
npm ci
npm run dev
```

Vite открывает интерфейс на `http://localhost:5173` и проксирует `/api`,
включая WebSocket логов, на `http://localhost:8000`.

Проверки из корня проекта:

```bash
python -m pip install -r backend/requirements-dev.txt
cd backend
python -m pytest -q
cd ../frontend
npm ci
npm run build
npm run gen:api
```

После генерации проверь изменения `frontend/src/api-types.ts` и включи их в коммит,
если изменился контракт API.

### Типы API для фронтенда

`frontend/src/api-types.ts` генерируется из OpenAPI-схемы бэкенда и коммитится:

```bash
cd frontend && npm run gen:api
```

Скрипт берёт Python из `./.venv` (или `$PYTHON`, или `python` из PATH),
экспортирует схему через `backend/export_openapi.py` и прогоняет её через
`openapi-typescript`. `src/types.ts` содержит только короткие алиасы на
сгенерированные типы. После изменения `backend/app/schemas.py` или роутов
нужно перегенерировать файл — CI сравнивает его с актуальной схемой и падает,
если он устарел.

### Пайплайн

- **CI** (`.github/workflows/ci.yml`): на каждый PR и пуш в `main` гоняются тесты
  бэкенда, typecheck/сборка фронтенда и проверка актуальности `api-types.ts`.
  Ничего не публикуется.
- **Релиз** (`.github/workflows/release.yml`): срабатывает на пуш тега `v*`.
  Проверяет, что тег совпадает с `VERSION`, прогоняет тесты, собирает фронтенд,
  упаковывает `LlamaPanel-v<version>.zip` (+ `.sha256`) и создаёт GitHub Release
  со списком коммитов с предыдущего тега.

Выпустить новую версию можно двумя способами.

**Через GitHub Actions** (`.github/workflows/bump-version.yml`): Actions → «Bump
version» → Run workflow → ввести `0.2.0`. Workflow проверит формат и что версия
растёт, запишет `VERSION`, закоммитит в `main`, поставит тег `v0.2.0` и запушит.
Дальше сработает `release.yml`. Требует секрет `RELEASE_TOKEN` (fine-grained PAT
с правом Contents: Read and write только на этот репозиторий), потому что тег,
запушенный стандартным `GITHUB_TOKEN`, не запускает другие workflow.

**Руками:**

```bash
echo 0.2.0 > VERSION
git commit -am "Bump version to 0.2.0"
git tag v0.2.0
git push && git push origin v0.2.0
```

