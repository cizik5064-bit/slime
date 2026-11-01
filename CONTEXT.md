# CONTEXT — рабочая память проекта Slime

Этот файл — внутренний контекст для будущих сессий агента и для пользователя.
Он не является пользовательской документацией (это `README.md`).

Последнее обновление: 2026-11-02
Версия проекта: **0.1.0 (pre-release, не выпущена)**

---

## 1. Что за проект

**Slime** — менеджер серверов Minecraft на Python с двумя интерфейсами:

- **TUI** на Textual — для новичков: список серверов, мастер создания,
  живая консоль, менеджер Java, диагностика.
- **CLI** на Typer — для автоматизации и скриптов.

Главная идея: провести новичка от «хочу сервер» до работающего Paper-сервера,
не заставляя искать jar, Java, EULA и свободный порт.

Расположение: `C:\Users\dylan\Desktop\Slime`
Пакет: `slime-mc`, импорт: `slime`, entry point: `slime`.
Лицензия: MIT. Язык интерфейса, кода и README — **английский**.
Язык общения с пользователем — **русский**.

---

## 2. Решения пользователя (зафиксировано)

| Вопрос | Решение |
| --- | --- |
| Язык Python | **3.11+** |
| ОС | **Windows 10+** и **Linux**; macOS — «should work» |
| Windows 7/8/8.1 | Отдельные legacy-сборки **позже**; в текущей ветке не поддерживаются (Python 3.11+ туда не ставится) |
| TUI | **Textual** |
| CLI | **Typer + Rich** |
| Ядра | Только проекты **PaperMC Fill API v3**: Paper, Folia, Velocity, Waterfall |
| Java | **Eclipse Temurin через Adoptium API v3** |
| Хранение | **`~/.slime`** (переопределяется `SLIME_HOME` / `--home`) |
| Язык UI/доков | **English** |
| EULA | Только явное согласие (`--accept-eula` или интерактивный вопрос). Никогда не принимать автоматически |
| Первая версия | Создание/запуск/остановка + консоль, проверки окружения, Java-менеджер |
| Вне скоупа v1 | Бэкапы, браузер плагинов/модов, редактор properties как отдельный экран, RCON |

Пользователь отдельно просил попробовать `curl.exe` для проверки сети
(в системе он есть). На 2026-11-02 сеть работает: Fill API v3 и Adoptium API
v3 отвечают HTTP 200.

---

## 3. Что уже сделано

### Код (написан, синтаксически проверен)

```
src/slime/
  __init__.py            версия 0.1.0, константы
  __main__.py            python -m slime
  errors.py              SlimeError + подклассы с hint
  config.py              Settings/Paths/Config, TOML без tomli-w
  models.py              Project, Server, BuildInfo, JavaInstall, валидация,
                         version_key/sort_versions, required_java_major
  properties.py          парсер/писатель server.properties, eula.txt
  store.py               реестр servers/<name>/slime.json, PID-файлы
  provision.py           создание сервера: build → download → конфиги
  java.py                JavaManager: установка/поиск/удаление Temurin
  checks.py              doctor: Python/OS/диск/RAM/порт/EULA/jar/Java
  process.py             asyncio-процесс, живая консоль, stop по stdin
  logging_setup.py       лог в ~/.slime/logs/slime.log
  cli.py                 все команды Typer
  api/
    papermc.py           Fill API v3 (tolerant parser)
    adoptium.py          Adoptium API v3 (архивы JDK)
  utils/
    downloads.py         потоковая загрузка + SHA-256 + прогресс
    archives.py          безопасная распаковка zip/tar.gz, поиск bin/java
  tui/
    app.py               SlimeApp, процессы, навигация
    app.tcss             стили
    screens/
      dashboard.py       таблица серверов
      server.py          консоль, start/stop/restart/delete
      create.py          мастер создания
      java.py            установка/удаление JDK
      doctor.py          проверки
      confirm.py         подтверждение удаления
```

### Реализованные команды

- `slime` / `slime tui`
- `slime doctor [--server] [--json]`
- `slime server list|create|info|run|eula|delete|path|versions|builds`
- `slime java list|releases|install|remove|which`
- `slime config show|set|path`

### Проверено локально

- `python -m compileall -q src` — **OK**.
- Отдельный скрипт проверил чистую логику (без сторонних зависимостей):
  сортировка версий, маппинг Java, валидация имён, round-trip `Server`,
  парсинг/экранирование properties, EULA, `Config` + сохранение TOML,
  распаковка zip и защита от path traversal — **все проверки прошли**.
- Создано окружение `.venv` (Python 3.14.8), установлены зависимости из
  `.[dev]`: typer 0.27.3, rich 14.3.4, textual 2.1.2, httpx 0.28.1,
  psutil 7.2.2, pytest 9.2.0, respx, ruff, mypy.
- `slime --version` → `Slime 0.1.0`.
- `slime doctor` на временном `SLIME_HOME` → exit 0, 4 ok / 2 info.
- Живые API: `server versions --project paper`, `server builds 1.21.4`,
  `server builds 26.3`, `java releases` — работают.
- TUI headless-смоук через `App.run_test`: dashboard → create → java →
  doctor → quit — **OK**.
- `pytest` — **215 passed**; `ruff check .` — **clean**;
  `mypy` — **no issues in 28 source files**.

### Исправлено после первой живой проверки (2026-11-02)

1. **Fill API v3 изменил формат.** `/projects` теперь возвращает список
   объектов `{"project": {...}, "versions": {...}}`, а
   `/projects/{project}/versions` — `{"versions": [{"version": {"id": ...},
   "builds": [...]}, ...]}`. Парсеры `projects()` и `version_groups()`
   обновлены и остаются терпимыми к старому dict-формату.
2. **Java для календарных версий.** Minecraft 26.1+ требует Java 25;
   `required_java_major()` теперь возвращает 25 для major ≥ 26.
3. **Textual 2.x.** Модуль `textual.work` удалён; импорты заменены на
   `from textual import work`.
4. **Циклический импорт TUI.** Экраны больше не импортируют `SlimeApp` в
   runtime: `TYPE_CHECKING` + `cast("SlimeApp", ...)`. Импорт TUI работает.
5. **`ServerStore.write_pid()`** теперь создаёт родительскую директорию,
   поэтому PID-файл можно записать до создания каталога сервера.
6. **Стиль кода.** `Enum` заменён на `StrEnum`, BINDINGS типизированы через
   `ClassVar`, убраны небезопасные `try/except/pass`, исправлены импорты.
   `ruff check .` и `mypy` проходят без ошибок.

### Что НЕ сделано / не проверено

1. **Тесты pytest написаны и проходят: 215 passed.** Покрыты
   `test_models.py`, `test_properties.py`, `test_config.py`,
   `test_store.py`, `test_checks.py`, `test_papermc.py`, `test_adoptium.py`,
   `test_provision.py`, `test_process.py`, `test_cli.py`, `test_archives.py`,
   `test_downloads.py`, `test_java.py`.
2. **TUI проверен только headless-смоуком**, не полным ручным сценарием:
   создание реального сервера, установка Java, запуск/остановка.
3. ~~`ruff check .` и `mypy` не чистые~~ — **исправлено**: оба проходят
   без ошибок.
4. ~~Git-репозиторий ещё не инициализирован~~ — **сделано** (ветка `main`,
   первый коммит).
5. ~~Нет `LICENSE`, `.gitignore`, `.gitattributes`, CI, `CHANGELOG.md`,
   `CONTRIBUTING.md`~~ — **сделано**. Добавлены MIT `LICENSE`, `.gitignore`,
   `.gitattributes`, `CHANGELOG.md` (Keep a Changelog), `CONTRIBUTING.md` и
   GitHub Actions CI (`.github/workflows/ci.yml`: Windows + Linux,
   Python 3.11–3.14, ruff, mypy, pytest, сборка sdist/wheel). `docs/` пока нет.
6. **Нет** реального релиза/скриншотов TUI/PyPI-публикации. Локальная сборка
   `python -m build` проверена: sdist и wheel создаются.
7. **Нет** кросс-процессного `stop`: сервер живёт, пока жив процесс Slime
   (TUI или foreground CLI). Это осознанное решение для v1: на Windows нельзя
   надёжно писать в stdin чужого процесса без RCON. В TUI stop работает, в CLI —
   Ctrl+C или команда `stop` в консоли.

---

## 4. Технические детали и риски

### PaperMC Fill API v3

- База: `https://fill.papermc.io/v3`
- Обязателен описательный `User-Agent`.
- Эндпоинты: `/projects`, `/projects/{project}/versions`,
  `/projects/{project}/versions/{version}/builds`,
  `/projects/{project}/versions/{version}/builds/{build}`.
- Выбор скачивания: ключ `server:default`, затем `server`, затем любой с
  `server` в имени.
- Каналы: `STABLE` / `BETA` / `ALPHA`. `latest_build` сначала ищет запрошенный
  канал, иначе берёт самый новый build.
- Парсер терпим к обёрткам `{"projects": ...}`, `{"versions": ...}`,
  `{"builds": ...}` и к прямым спискам.
- Актуальный формат (2026-11): проекты и версии приходят списками объектов.
  `_project_id()` и `_version_id()` разворачивают `{"project": ...}`,
  `{"version": {"id": ...}}`, `{"id": ...}` и строки.
- `/projects` также отдаёт `travertine`; Slime его не поддерживает и просто
  игнорирует при выборе проекта через модель `Project`.

### Adoptium API v3

- База: `https://api.adoptium.net/v3`
- `/info/available_releases`
- `/assets/latest/{major}/hotspot?architecture=...&image_type=jdk&os=...&vendor=eclipse&project=jdk`
- Скачивается `binary.package` (архив, не installer), проверяется
  `package.checksum` (SHA-256), распаковывается в `~/.slime/java`.
- Маппинг ОС: Windows → `windows`, Linux → `linux`, macOS → `mac`.
- Маппинг архитектур: `AMD64/x86_64` → `x64`, `aarch64/arm64` → `aarch64`.

### Java по умолчанию

- Paper/Folia: `<= 1.16.5` → 8; `1.17–1.20.4` → 17; `1.20.5–1.21.x` → 21;
  календарные `26.x+` → 25 (Fill указывает минимум Java 25);
  снапшоты → 21.
- Velocity → 17, Waterfall → 11.
- Разрешённые majors в модели: 8, 11, 16, 17, 21, 25.

### Хранение

```
~/.slime/config.toml
~/.slime/servers/<name>/slime.json
~/.slime/servers/<name>/server.jar
~/.slime/servers/<name>/server.properties
~/.slime/servers/<name>/eula.txt
~/.slime/java/temurin-<major>-<os>-<arch>/
~/.slime/java/.../slime-java.json
~/.slime/logs/slime.log
~/.slime/logs/<server>.log
```

`server.properties` создаётся только если его нет; существующие значения не
перезаписываются. Порт из `slime.json` и `server.properties` сверяется в
`doctor` (warning при расхождении).

### Процессы

- `asyncio.create_subprocess_exec`, `stdin=PIPE`, `stdout=PIPE`, `stderr=STDOUT`.
- Команда: `java -Xms{mem}M -Xmx{mem}M -Dfile.encoding=UTF-8 -jar server.jar`.
- `--nogui` добавляется только для Paper/Folia (не для прокси).
- `JAVA_HOME` выставляется в домашнюю папку выбранного JDK.
- Статус `RUNNING` выставляется по строке `Done (` / `Listening on /`.
- PID пишется в `slime.pid`; при выходе удаляется.
- Логи пишутся в `~/.slime/logs/<server>.log` и в ring buffer (3000 строк).

### Известные места, требующие runtime-проверки

1. **Textual API**: `Select.set_options`, `Select.BLANK`, `DataTable.RowSelected`,
   `App.call_from_thread`, `App.action_quit` как async, CSS-свойства
   (`max-height`, `overflow-y`, `$background 60%`). Импорт `work` уже исправлен
   под Textual 2.x; полный ручной сценарий ещё не пройден.
2. **Typer**: `Annotated` + `typer.Option` с `envvar`, `--accept/--revoke`,
   вложенные `add_typer`, `invoke_without_command`, eager `--version` —
   проверено запуском `--version`, `doctor`, `server versions/builds`,
   `java releases`.
3. **Windows**: `signal.signal(SIGINT, ...)` в главном потоке; `asyncio` на
   Windows должен использовать Proactor loop (по умолчанию в 3.11+).
   `Process.terminate()` на Windows — жёсткое завершение; сначала отправляем
   `stop` через stdin.
4. **`find_java_executable`** на Windows ищет `java.exe`, на POSIX — `java`.
   В тестовой фикстуре это учтено.
5. **Циклические импорты TUI**: исправлено — экраны используют
   `TYPE_CHECKING` и `cast("SlimeApp", ...)`.
6. **`CreateServerScreen`**: `Select.set_options` сбрасывает значение; после
   установки опций выставляется `""`. Нужно проверить, что Textual 2.x
   разрешает значение `""` (иначе заменить на `"latest"`); headless-смоук
   экран открывает, но создание сервера не прогонялось.
7. **`DashboardView.cursor_row`**: в старых Textual это `int`, в новых может
   быть `None`; код устойчив к `None`, но проверить.

---

## 5. Как запускать и разрабатывать

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux:
source .venv/bin/activate

pip install -e ".[dev]"
ruff check .
pytest
slime --version
slime
```

Если сети нет, установить зависимости нельзя; код всё равно можно проверить:

```powershell
python -m compileall -q src
```

Быстрая проверка чистой логики без зависимостей — импортировать
`slime.models`, `slime.properties`, `slime.config`, `slime.utils.archives`
(они используют только stdlib).

---

## 6. Правила работы (важно для будущих сессий)

### Версионирование

- Текущая версия — **0.1.0**, это **pre-release**.
- **После релиза первой версии** (первый публичный релиз, то есть `1.0.0`)
  каждое существенное изменение программы должно сопровождаться **повышением
  версии**:
  - bugfix / небольшое изменение — patch (`1.0.0` → `1.0.1`);
  - новая функциональность — minor (`1.0.1` → `1.1.0`);
  - несовместимые изменения — major (`1.1.0` → `2.0.0`).
- При повышении версии синхронно обновлять:
  - `pyproject.toml` → `[project].version`;
  - `src/slime/__init__.py` → `__version__`;
  - `CHANGELOG.md` (создать, если ещё нет).
- До первого релиза версию тоже менять осмысленно, но правило «каждое
  существенное изменение = bump» становится обязательным **после** `1.0.0`.

### CONTEXT.md

- Обновлять `CONTEXT.md` **по просьбе пользователя**.
- Также обновлять при изменении архитектуры, зависимостей, правил или
  статуса «сделано/не сделано», если пользователь явно попросил поддерживать
  файл в актуальном состоянии.
- Не переписывать этот файл без необходимости и не удалять исторические
  решения пользователя.

### Стиль ответов

- Общаться с пользователем **по-русски**, кратко и по делу.
- Код, имена, UI-строки, README, docstrings — **на английском**.
- Не утверждать, что что-то протестировано, если это не так. Чётко разделять
  «написано», «проверено статически», «проверено вживую».
- Перед удалением/перезаписью чужих файлов — проверять, что это не работа
  пользователя.
- Для деструктивных операций (удаление сервера, JDK, перезапись конфигов)
  требовать подтверждение, если пользователь явно не передал `--yes`.
- EULA никогда не принимать автоматически.
- Секреты, токены и персональные данные не логировать.

---

## 7. Следующие шаги (приоритет)

1. ~~Проверить сеть (`curl.exe`) и установить зависимости.~~ — **сделано**.
2. ~~Запустить `slime --version`, `slime doctor`, `slime server versions`,
   `slime java releases` — проверить реальные ответы API.~~ — **сделано**,
   найдены и исправлены баги Fill API и Java 26.x.
3. Пройти полный TUI-сценарий: создание реального сервера, установка Java,
   запуск/консоль/остановка.
4. ~~Дописать тесты (см. список в разделе 3) и прогнать `pytest`.~~ —
   **сделано**, 215 passed.
5. ~~Привести `ruff check .` и `mypy` к чистому состоянию.~~ — **сделано**.
6. ~~Добавить `LICENSE` (MIT), `.gitignore`, `.gitattributes`,
   `CHANGELOG.md`, `CONTRIBUTING.md`, CI (GitHub Actions: Windows + Linux,
   Python 3.11–3.14).~~ — **сделано**.
7. ~~Инициализировать git, сделать первый коммит.~~ — **сделано**.
8. Подготовить релиз `1.0.0` после стабилизации (пока не начиналось:
   остаётся живой TUI-сценарий и публикация).

---

## 8. Полезные ссылки

- PaperMC Fill API: https://docs.papermc.io/misc/download-api/
- Adoptium API: https://api.adoptium.net/q/swagger-ui/
- Minecraft EULA: https://aka.ms/MinecraftEULA
- Textual: https://textual.textualize.io/
- Typer: https://typer.tiangolo.com/
