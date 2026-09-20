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

При обновлении можно распаковать новый zip поверх той же папки или в новую —
пресеты и лог `llama-server` лежат не в папке установки, а в пользовательской
директории данных (см. ниже), поэтому при переезде не теряются. `config.ini`
и `.venv/` лежат рядом с `run.py` и в архив не входят.

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

Если `models_dir` не задан, по умолчанию используется `models/` рядом с `run.py`
(не относительно текущей директории). `data_dir` (пресеты, лог `llama-server`)
по умолчанию — пользовательская директория **вне** папки установки, чтобы
новая версия, распакованная в другое место, видела те же пресеты:

| ОС      | Путь                                                     |
|---------|----------------------------------------------------------|
| Windows | `%LOCALAPPDATA%\LlamaPanel`                              |
| macOS   | `~/Library/Application Support/LlamaPanel`               |
| Linux   | `$XDG_DATA_HOME/llamapanel` (обычно `~/.local/share/llamapanel`) |

Фактический путь печатается при старте `run.py`. Если в `data_dir` пресетов
ещё нет, а в `data/` рядом с `run.py` (старое место) они есть — файл копируется
туда при первом запуске.

### Хранение пресетов

`presets.json` — версионированный документ (`{"version": N, "app_version": ...,
"presets": [...]}`, см. `app/storage.py`). При обновлении формата файл
мигрируется на лету, а перед этим сохраняется копия `presets.json.vN.bak`. Файл
от более новой версии панели не перезаписывается — API вернёт понятную ошибку.
Невалидный JSON откладывается в `presets.json.corrupt-<дата>`, а не затирается.

Флаги в пресетах приводятся к текущей схеме при каждом чтении
(`FlagCatalog.resolve` в `app/flags.py`): ключ ищется по любому написанию
флага, которое знает установленный `llama-server` (`--n-gpu-layers` и
`--gpu-layers` — один флаг), старый ключ вида `no_kv_offload` превращается в
`kv_offload` с инверсией значения, изменившийся тип приводится автоматически.
Ключи, которых текущая сборка не знает, сохраняются как есть и отдаются в поле
`unsupported`, чтобы UI мог предупредить, а не молча выбросить. Для
переименований, которые не покрываются псевдонимами, остаётся `FLAG_RENAMES`.

Параметры можно задать и через переменные окружения вместо флагов:
`LLAMAPANEL_HOST`, `LLAMAPANEL_PORT`, `LLAMAPANEL_MODELS_DIR`,
`LLAMAPANEL_SERVER_BIN`, `LLAMAPANEL_DATA_DIR`, `LLAMAPANEL_LOG_BUFFER_SIZE`.
Старые имена `LLAMA_MODELS_DIR` и `LLAMA_SERVER_BIN` тоже работают.

Версия приложения хранится в файле `VERSION` и отдаётся в `GET /api/health`.

## Разработка и релизы

### Структура бэкенда

- `app/settings.py` — `Settings`: один неизменяемый объект со всей конфигурацией.
  `run.py` собирает его (CLI > `config.ini` > env > дефолты) и передаёт в
  `create_app(settings)`; при импорте ничего не читается из окружения и не
  создаётся на диске.
- `app/main.py` — `create_app()`: фабрика приложения. В `lifespan` создаются
  `ProcessManager`, `LlamaClient` и `PresetStore`, кладутся в `app.state` и
  корректно закрываются при остановке панели (сам `llama-server` при этом не
  убивается — следующий запуск панели подхватит его через discovery).
- `app/deps.py` — зависимости `SettingsDep`, `ManagerDep`, `PresetsDep`, через
  которые роутеры получают эти объекты. Глобальных синглтонов нет.
- `app/storage.py` — `JsonDocumentStore`: версионированный JSON-файл с
  миграциями, бэкапом перед миграцией и атомарной записью. `app/presets.py`
  — `PresetStore` поверх него (формат пресетов и его история).
- `app/introspection.py` — `BinaryInspector`: запускает `llama-server --version`
  и `--help`, разбирает вывод в структурированный список опций (имена, тип,
  дефолт, варианты, описание, секция) и кэширует его, пока бинарник на диске
  не изменится. Отдаётся через `GET /api/server/binary`.
- `app/flags.py` — `FlagCatalog`: схема формы (`GET /api/server/flags`)
  строится из этого списка, а не из зашитого набора. Поверх накладывается
  небольшой кураторский слой `CURATED` (человеческие названия, что считать
  «basic», закреплённые ключи пресетов) и список `HIDDEN` того, чем управляет
  сама панель (`--model`, `--help`, скачивание весов, логи). Если бинарник не
  найден, используется снимок `--help` из `app/snapshots/llama-server-help.txt`
  (он же фикстура для тестов парсера). Там же `build_args` (значения, равные
  документированному дефолту, в командную строку не попадают; булевы флаги с
  парой `--x/--no-x` выключаются через `--no-x`; повторяемые флаги принимают
  список) и обратный `parse_args` для подхвата чужого процесса.
- `app/llama_client.py` — единственное место, где панель ходит по HTTP к
  `llama-server` (`/health`, `/slots`). Состояние `starting` настоящее:
  процесс запущен, но `/health` ещё отвечает 503, пока грузится модель;
  `running` — только после 200.

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

## Лицензия

[MIT](LICENSE).


### Multiple server instances

The **Servers** page lists independent llama-server instances. Use **Create server**
to assign a name and unique API port, then open it to choose a model and configure
its flags. **Save configuration** persists changes without restarting;
**Start** and **Apply & restart** also save the requested configuration.
Draft edits survive navigation between instances within the current page session.
Models and presets are shared; applying a preset does not change the instance port.
The panel passes that port explicitly to llama-server.

Each instance has its own process, readiness checks, restart queue and log stream.
Ports are reserved across saved instances (even when stopped); an occupied external
port is rejected before start. Stop an instance before changing its port or deleting
it. Deleting its configuration does not delete model files, presets or log files.
The default instance remains available for older API clients.

Configurations and process identities are stored in `instances.json` in the panel's
data directory. Additional instance logs live in `instances/<id>/llama-server.log`;
the default instance retains the original log path. Closing the panel leaves the
processes running. On the next launch, recorded PIDs are checked against creation
time and executable identity before adoption. There is no automatic start of stopped
instances. Pending restart requests are cancelled when the panel shuts down.
Use one panel process per data directory. Available RAM/VRAM still limits how many
models can run simultaneously; the panel does not allocate GPU memory for you.

Instance configuration API: `GET/POST /api/instances`,
`PUT/DELETE /api/instances/{id}`. Existing `/api/server/status`, `/start`, `/stop`,
`/restart`, `/restart/cancel` and the logs WebSocket accept `?instance_id=<id>`.
Omitting it targets `default`. `/flags` and `/binary` remain shared.
