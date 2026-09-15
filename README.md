# LlamaPanel

Model-serving панель для `llama-server` (llama.cpp): сканирует директорию с GGUF-моделями,
запускает/останавливает сервер с выбранными флагами, показывает статус и живые логи.
Сам `llama-server` поднимает OpenAI-совместимый API на своём порту — на него может
указывать любой внешний клиент/агент (например Hermes), не зная о деталях запуска.

Панель рассчитана на то, что она **работает на той же машине, где лежат
llama.cpp и модели** — процесс `llama-server` запускается как локальный сабпроцесс.

## Установка

### Вариант 1: готовый релиз (рекомендуется)

Скачай zip из [Releases](../../releases) — в нём фронтенд уже собран, на целевой
машине нужен **только Python 3.12+**, Node.js не требуется.

```bash
unzip LlamaPanel-<version>.zip
cd LlamaPanel
cp config.example.ini config.ini
# отредактировать config.ini: models_dir, server_bin, host/port
python run.py
```

При обновлении распаковывай новый zip **поверх** той же папки: `config.ini`,
`.venv/` и `data/` (пресеты, лог) лежат рядом с `run.py` и в архив не входят.

### Вариант 2: из исходников

Собранного фронтенда в репозитории нет — его нужно собрать один раз (нужен Node.js 20+):

```bash
git clone <repo> LlamaPanel
cd LlamaPanel/frontend && npm ci && npm run build && cd ..
cp config.example.ini config.ini
python run.py
```

Без `frontend/dist/` бэкенд всё равно поднимется, но по адресу панели вместо UI
будет текстовая подсказка, как его собрать.

Вместо `config.ini` те же параметры можно передать разово через CLI-флаги
(`--models-dir`, `--llama-bin`, `--host`, `--port`, `--data-dir`) — они всегда
побеждают файл. Приоритет: **CLI-флаг > `config.ini` > переменная окружения >
встроенный дефолт**. `config.ini` в `.gitignore` — свой путь к моделям туда
пишешь один раз на машине и не таскаешь в git.

Первый запуск сам:
1. создаёт venv в `./.venv` (используя тот Python, которым запущен `run.py`);
2. переисполняет себя внутри этого venv;
3. ставит туда зависимости backend'а (`pip install -r backend/requirements.txt`).

На системный Python это ничего не ставит — только на его основе создаётся
изолированный venv. Повторные запуски — быстрый no-op (venv и зависимости уже
на месте). Открыть `http://<ip-этой-машины>:8000` (или `--host 0.0.0.0`, если
нужен доступ не только с localhost).

Если `models_dir` / `data_dir` не заданы, по умолчанию используются `models/` и
`data/` рядом с `run.py` (не относительно текущей директории).

Параметры можно задать и через переменные окружения вместо флагов:
`LLAMAPANEL_HOST`, `LLAMAPANEL_PORT`, `LLAMAPANEL_MODELS_DIR`,
`LLAMAPANEL_SERVER_BIN`, `LLAMAPANEL_DATA_DIR`, `LLAMAPANEL_LOG_BUFFER_SIZE`.
Старые имена `LLAMA_MODELS_DIR` и `LLAMA_SERVER_BIN` тоже работают.

Версия приложения хранится в файле `VERSION` и отдаётся в `GET /api/health`.

## Разработка и релизы

- **CI** (`.github/workflows/ci.yml`): на каждый PR и пуш в `main` гоняются тесты
  бэкенда и typecheck/сборка фронтенда. Ничего не публикуется.
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

## Лицензия

[MIT](LICENSE).
