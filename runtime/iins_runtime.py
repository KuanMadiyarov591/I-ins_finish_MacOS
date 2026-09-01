"""I-ins — единый локальный запуск шести кабинетов на macOS.

Запускается из виртуального окружения, которое готовит I-ins.command.
PyInstaller не используется: программа работает как обычный Python-код,
поэтому одна и та же поставка подходит и Apple Silicon, и Intel.

Режимы:
    python iins_runtime.py                  окно I-ins и все шесть модулей
    python iins_runtime.py --self-check     проверка окружения без запуска модулей
    python iins_runtime.py --smoke-test     запуск и проверка всех модулей без окна
    python iins_runtime.py --force-extract  переустановить payload заново
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import platform
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import warnings
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

APP_NAME = "I-ins"
APP_VERSION = "1.2.0-macos"
HOST = "127.0.0.1"

# Версии, которыми обучены встроенные .joblib-модели.
# Несовпадение не блокирует запуск, но попадает в журнал и в самопроверку.
MODEL_TRAINED_SKLEARN = "1.9.0"

# Контрольные значения полной базы знаний: 109 PDF, 7499 фрагментов в шести хранилищах.
EXPECTED_TOTAL_CHUNKS = 7499
EXPECTED_PDF_FILES = 110


@dataclass(frozen=True)
class Service:
    key: str
    title: str
    description: str
    package: str
    port: int
    login: str
    password: str
    database: str
    expected_service: str
    surface: str = ""
    # У кабинетов клиента и администратора RAG живёт на /api/rag,
    # у остальных четырёх — внутри /api/assistant.
    rag_status_path: str = "api/rag/status"
    rag_ask_path: str = "api/rag/ask"
    min_chunks: int = 1

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"


ASSISTANT_STATUS = "api/assistant/rag/status"
ASSISTANT_ASK = "api/assistant/ask"

SERVICES: tuple[Service, ...] = (
    Service("client", "Клиент", "Полисы, обращения и страховые сервисы",
            "iins_client_app", 8000, "client", "client123",
            "insurance.db", "insurance-rag-system", "client",
            min_chunks=407),
    Service("agent", "Страховой агент", "CRM, подбор продуктов и сопровождение",
            "iins_agent_app", 8002, "agent", "agent123",
            "agent.db", "insurance-agent-desk", "",
            ASSISTANT_STATUS, ASSISTANT_ASK, 413),
    Service("admin", "Администратор", "Управление системой и справочниками",
            "iins_admin_app", 8003, "admin", "admin123",
            "insurance.db", "insurance-rag-system", "admin",
            min_chunks=1081),
    Service("underwriter", "Андеррайтер", "Оценка риска и условия страхования",
            "iins_underwriter_app", 8004, "underwriter", "uw123",
            "underwriter.db", "insurance-underwriter-desk", "",
            ASSISTANT_STATUS, ASSISTANT_ASK, 811),
    Service("legal", "Юрист", "Правовая экспертиза и документы",
            "iins_legal_app", 8005, "lawyer", "lawyer123",
            "legal.db", "legal-hub", "",
            ASSISTANT_STATUS, ASSISTANT_ASK, 2185),
    Service("actuary", "Актуарий", "Тарифы, резервы и аналитика",
            "iins_actuary_app", 8006, "actuary", "actuary123",
            "actuary.db", "actuarial-desk", "",
            ASSISTANT_STATUS, ASSISTANT_ASK, 2602),
)


def active_services() -> tuple[Service, ...]:
    """Рабочие порты либо смещённые — так smoke-test не конфликтует с обычным запуском."""
    raw = os.getenv("IINS_PORT_OFFSET", "0")
    try:
        offset = int(raw)
    except ValueError as exc:
        raise ValueError(f"IINS_PORT_OFFSET должен быть целым числом, получено {raw!r}") from exc
    if offset == 0:
        return SERVICES
    if offset < 0 or SERVICES[-1].port + offset > 65535:
        raise ValueError(f"Недопустимый IINS_PORT_OFFSET: {offset}")
    return tuple(
        Service(s.key, s.title, s.description, s.package, s.port + offset,
                s.login, s.password, s.database, s.expected_service, s.surface,
                s.rag_status_path, s.rag_ask_path, s.min_chunks)
        for s in SERVICES
    )


# --------------------------------------------------------------------------- пути


def data_root() -> Path:
    override = os.getenv("IINS_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        # На учебных Mac домашняя квота мала, а локальный диск смонтирован
        # как ~/goinfre: если он есть, рабочая папка идёт туда.
        goinfre = Path.home() / "goinfre"
        if goinfre.is_dir():
            return goinfre / APP_NAME
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "i-ins"


def package_root() -> Path:
    return Path(__file__).resolve().parent


def payload_archive() -> Path:
    override = os.getenv("IINS_PAYLOAD_ZIP")
    candidate = Path(override).expanduser().resolve() if override else package_root() / "payload.zip"
    if not candidate.is_file():
        raise FileNotFoundError(
            f"Не найден payload.zip: {candidate}\n"
            "Распакуйте архив I-ins полностью, не перемещая файлы из папки runtime."
        )
    return candidate


# ------------------------------------------------------------------ GigaChat

GIGACHAT_BASE_URL = "https://gigachat-students.nsk.21-school.ru/v1"
GIGACHAT_MODEL = "Gigashlep/GigaChat-2-Max"


def gigachat_key() -> str:
    """Ключ GigaChat: переменная окружения либо файл gigachat.key.

    Ключ намеренно не хранится в исходном коде: файл gigachat.key лежит рядом
    с I-ins.command и в репозиторий не попадает.
    """
    for var in ("GIGACHAT_API_KEY", "IINS_GIGACHAT_KEY"):
        value = (os.getenv(var) or "").strip()
        if value:
            return value
    candidates = (
        package_root().parent / "gigachat.key",
        package_root() / "gigachat.key",
        Path.home() / ".i-ins" / "gigachat.key",
    )
    for path in candidates:
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:
            continue
    return ""


def gigachat_probe(timeout: float = 8.0) -> tuple[bool, str]:
    """Проверяет доступность GigaChat. Возвращает (готов, пояснение)."""
    key = gigachat_key()
    if not key:
        return False, "ключ не задан — положите его в файл gigachat.key рядом с I-ins.command"
    url = (os.getenv("GIGACHAT_BASE_URL") or GIGACHAT_BASE_URL).rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status < 400, f"сервис отвечает ({response.status})"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, "ключ отклонён сервисом"
        if exc.code in (404, 405):
            return True, "сервис доступен"
        return False, f"сервис ответил ошибкой {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"нет связи: {exc}"


SMOKE_QUESTION_DEFAULT = "Какие обязанности сторон и порядок урегулирования предусмотрены?"

# Кабинет актуария отвечает по тарифному корпусу: общий вопрос об урегулировании
# отсекается порогом релевантности, и это правильное поведение, а не сбой.
SMOKE_QUESTIONS = {
    "actuary": "Как рассчитывается страховая премия и какие допущения применяются при тарификации?",
}


def smoke_question(key: str) -> str:
    return SMOKE_QUESTIONS.get(key, SMOKE_QUESTION_DEFAULT)


def payload_archive_optional() -> Path | None:
    """payload.zip, если он есть; None — если комплект лежит распакованным."""
    override = os.getenv("IINS_PAYLOAD_ZIP")
    candidate = Path(override).expanduser().resolve() if override else package_root() / "payload.zip"
    return candidate if candidate.is_file() else None


def inplace_payload() -> Path | None:
    """Комплект, лежащий распакованным рядом с программой (как в репозитории)."""
    override = os.getenv("IINS_PAYLOAD_DIR")
    candidates = [Path(override).expanduser()] if override else []
    candidates += [package_root().parent / "payload", package_root() / "payload"]
    for path in candidates:
        try:
            if (path / "modules").is_dir():
                return path.resolve()
        except OSError:
            continue
    return None


def verify_inplace(payload: Path) -> None:
    """Проверяет состав распакованного комплекта до запуска кабинетов."""
    missing = []
    for service in SERVICES:
        main = payload / "modules" / service.key / service.package / "main.py"
        if not main.is_file():
            missing.append(f"{service.key} ({main.name} не найден)")
    if missing:
        raise RuntimeError(
            "Комплект в " + str(payload) + " неполный: " + ", ".join(missing) + ".\n"
            "Скачайте репозиторий заново: git clone ... или распакуйте архив целиком."
        )


def runtime_dir(root: Path) -> Path:
    return root / f"runtime-{APP_VERSION}"


def state_dir(root: Path) -> Path:
    return root / "state"


# --------------------------------------------------------------------- вспомогательное


def _make_writable(path: Path, *, directory: bool) -> None:
    """Чинит права пользователя, которые теряются после копирования или сбоя."""
    try:
        info = path.lstat()
        flags = getattr(info, "st_flags", 0)
        immutable = getattr(stat, "UF_IMMUTABLE", 0)
        if flags and immutable and (flags & immutable) and hasattr(os, "chflags"):
            os.chflags(path, flags & ~immutable)
        required = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if directory else 0)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & required != required:
            path.chmod(mode | required)
    except OSError as exc:
        raise PermissionError(
            f"Нет прав на {path}.\n"
            f"Закройте I-ins и выполните: chmod -R u+rwX \"{data_root()}\""
        ) from exc


def prepare_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Ожидалась обычная папка, а найдено другое: {path}")
    _make_writable(path, directory=True)
    return path


def setup_logging(root: Path) -> Path:
    prepare_directory(root)
    log_dir = prepare_directory(root / "logs")
    log_file = log_dir / "I-ins.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    return log_file


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nfc_path(value: str) -> str:
    """Один вид записи пути для сравнения: APFS может отдавать имена в NFD, JSON хранит NFC."""
    return "/".join(unicodedata.normalize("NFC", part) for part in PurePosixPath(value).parts)


# ------------------------------------------------------------------ установка payload


def _plan_extraction(archive: zipfile.ZipFile, target: Path) -> list[tuple[zipfile.ZipInfo, Path]]:
    planned: list[tuple[zipfile.ZipInfo, Path]] = []
    seen: set[str] = set()
    resolved_target = target.resolve()
    for member in archive.infolist():
        name = member.filename
        pure = PurePosixPath(name)
        parts = tuple(part for part in pure.parts if part not in ("", "."))
        if pure.is_absolute() or not parts or ".." in parts or "\x00" in name or "\\" in name:
            raise RuntimeError(f"Недопустимый путь в payload: {name}")
        for part in parts:
            longest = max(len(part.encode("utf-8")),
                          len(unicodedata.normalize("NFD", part).encode("utf-8")))
            if longest > 255:
                raise RuntimeError(f"Имя в payload длиннее 255 байт: {name}")
        key = "/".join(unicodedata.normalize("NFD", part).casefold() for part in parts)
        if key in seen:
            raise RuntimeError(f"Коллизия имени в payload: {name}")
        seen.add(key)
        if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
            raise RuntimeError(f"Символьные ссылки в payload запрещены: {name}")
        destination = target.joinpath(*parts)
        resolved = destination.resolve()
        if resolved != resolved_target and resolved_target not in resolved.parents:
            raise RuntimeError(f"Выход за пределы папки установки: {name}")
        planned.append((member, destination))
    return planned


def _extract(archive: zipfile.ZipFile, target: Path,
             progress: Callable[[int, int], None] | None = None) -> None:
    planned = _plan_extraction(archive, target)
    total = len(planned)
    for index, (member, destination) in enumerate(planned, start=1):
        if member.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        if progress and (index % 25 == 0 or index == total):
            progress(index, total)


def _verify_tree(root: Path, manifest: dict[str, Any]) -> None:
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
        raise RuntimeError("Некорректный список файлов в payload_manifest.json")

    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name == "payload_manifest.json":
            continue
        canonical = nfc_path(path.relative_to(root).as_posix())
        if canonical in actual:
            raise RuntimeError(f"Unicode-коллизия файлов: {canonical}")
        actual[canonical] = path

    expected: set[str] = set()
    total_bytes = 0
    for entry in entries:
        relative = str(entry.get("path") or "")
        canonical = nfc_path(relative)
        path = actual.get(canonical)
        if path is None:
            raise RuntimeError(f"Файл из manifest отсутствует: {relative}")
        size = path.stat().st_size
        if size != int(entry.get("bytes", -1)):
            raise RuntimeError(f"Размер не совпал с manifest: {relative}")
        if sha256_file(path) != entry.get("sha256"):
            raise RuntimeError(f"SHA-256 не совпал с manifest: {relative}")
        expected.add(canonical)
        total_bytes += size

    if set(actual) != expected:
        missing = sorted(expected - set(actual))[:3]
        extra = sorted(set(actual) - expected)[:3]
        raise RuntimeError(f"Состав payload не совпал с manifest; нет={missing}; лишние={extra}")
    if total_bytes != int(manifest.get("uncompressed_bytes", -1)):
        raise RuntimeError("Общий размер payload не совпал с manifest")


def ensure_runtime(root: Path, *, force: bool = False,
                   progress: Callable[[str], None] | None = None) -> Path:
    """Ставит payload в ~/Library/Application Support/I-ins/runtime-<версия>."""
    # Комплект, лежащий распакованным, используется как есть: без сборки архива
    # и без второй копии в папке данных — это экономит около 400 МБ.
    payload_dir = inplace_payload()
    archive_path = payload_archive_optional()
    if payload_dir is not None and archive_path is None:
        if progress:
            progress("Комплект используется из папки payload — архив не нужен")
        verify_inplace(payload_dir)
        return payload_dir
    if archive_path is None:
        raise FileNotFoundError(
            "Не найден комплект: нет ни runtime/payload.zip, ни папки payload/modules.\n"
            "Распакуйте архив I-ins полностью или склонируйте репозиторий целиком."
        )

    target = runtime_dir(root)
    marker = target / ".iins-runtime-ready.json"
    info = archive_path.stat()

    if not force and marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        same_file = (saved.get("payload_bytes") == info.st_size
                     and saved.get("payload_mtime_ns") == info.st_mtime_ns)
        if saved.get("version") == APP_VERSION and (same_file or saved.get("payload_sha256") == sha256_file(archive_path)):
            return target

    if progress:
        progress("Проверка комплекта…")
    archive_sha = sha256_file(archive_path)
    expected_sha_file = archive_path.with_suffix(archive_path.suffix + ".sha256")
    if expected_sha_file.is_file():
        expected = expected_sha_file.read_text(encoding="utf-8").split()[0].strip()
        if expected and expected != archive_sha:
            raise RuntimeError(
                "payload.zip повреждён при копировании или загрузке.\n"
                "Скачайте и распакуйте архив I-ins заново."
            )

    prepare_directory(root)
    staging = Path(tempfile.mkdtemp(prefix=f"install-{APP_VERSION}-", dir=str(root)))
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            def report(done: int, total: int) -> None:
                if progress:
                    progress(f"Установка компонентов… {done * 100 // total}%")
            _extract(archive, staging, progress=report)

        manifest_path = staging / "payload_manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("В payload отсутствует payload_manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != APP_VERSION:
            raise RuntimeError(
                f"Версия payload {manifest.get('version')} не совпадает с runtime {APP_VERSION}"
            )
        if progress:
            progress("Проверка контрольных сумм…")
        _verify_tree(staging, manifest)

        (staging / ".iins-runtime-ready.json").write_text(
            json.dumps(
                {
                    "product": APP_NAME,
                    "version": APP_VERSION,
                    "payload_sha256": archive_sha,
                    "payload_bytes": info.st_size,
                    "payload_mtime_ns": info.st_mtime_ns,
                    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "python": platform.python_version(),
                    "machine": platform.machine(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


# ------------------------------------------------------------------- рабочая база


def prepare_state(root: Path) -> Path:
    state = prepare_directory(state_dir(root))
    for item in state.rglob("*"):
        if item.is_symlink():
            raise RuntimeError(f"Символьные ссылки в рабочей базе запрещены: {item}")
        _make_writable(item, directory=item.is_dir())

    probe = state / f".write-probe-{os.getpid()}.sqlite3"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(probe), timeout=5.0)
        connection.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO probe DEFAULT VALUES")
        connection.commit()
    except sqlite3.Error as exc:
        raise PermissionError(
            f"SQLite не может писать в {state}.\n"
            f"Закройте I-ins и выполните: chmod -R u+rwX \"{root}\""
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                Path(str(probe) + suffix).unlink(missing_ok=True)
            except OSError:
                pass
    return state


def sqlite_url(path: Path) -> str:
    prepare_directory(path.parent)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Некорректный путь базы данных: {path}")
        _make_writable(path, directory=False)
    return f"sqlite:///{path.resolve().as_posix()}"


def configure_environment(service: Service, module_root: Path, state: Path) -> None:
    """Настройки читаются модулем через pydantic-settings из переменных окружения."""
    offset = int(os.getenv("IINS_PORT_OFFSET", "0"))
    docs = prepare_directory(state / "docs" / service.key)
    os.environ.update(
        {
            "APP_HOST": HOST,
            "APP_PORT": str(service.port),
            "APP_SURFACE": service.surface or service.key,
            "CLIENT_PORT": str(8000 + offset),
            "ADMIN_PORT": str(8003 + offset),
            "DATABASE_URL": sqlite_url(state / service.database),
            "COMPANY_DB_FORCE_SQLITE": "1",
            "COMPANY_DATABASE_URL": sqlite_url(state / "company_insurance.db"),
            "DOCS_STORAGE_DIR": str(docs),
            "LM_BACKEND": os.getenv("IINS_LM_BACKEND", "auto"),
            "GIGACHAT_BASE_URL": os.getenv("GIGACHAT_BASE_URL", GIGACHAT_BASE_URL),
            "GIGACHAT_MODEL": os.getenv("GIGACHAT_MODEL", GIGACHAT_MODEL),
            "GIGACHAT_API_KEY": gigachat_key(),
            "PYTHONUTF8": "1",
        }
    )


# ----------------------------------------------------------------------- сеть


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((HOST, port)) == 0


def request_json(url: str, method: str = "GET", body: dict[str, Any] | None = None,
                 token: str = "", timeout: float = 10.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ------------------------------------------------------------------- менеджер


class RuntimeManager:
    def __init__(self, root: Path, *, force_extract: bool = False,
                 progress: Callable[[str], None] | None = None) -> None:
        self.root = root
        self.state = prepare_state(root)
        self.runtime = ensure_runtime(root, force=force_extract, progress=progress)
        self.services = active_services()
        self.servers: dict[str, Any] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.adopted: set[str] = set()
        self._register_paths()

    def _register_paths(self) -> None:
        """Все шесть корней остаются в sys.path: модули догружают подпакеты по запросу."""
        for service in self.services:
            module_root = self.runtime / "modules" / service.key
            if not module_root.is_dir():
                raise FileNotFoundError(f"Модуль не найден: {module_root}")
            text = str(module_root)
            if text not in sys.path:
                sys.path.insert(0, text)

    def load_app(self, service: Service) -> Any:
        module_root = self.runtime / "modules" / service.key
        configure_environment(service, module_root, self.state)
        module = importlib.import_module(f"{service.package}.main")
        return module.app

    def _adoptable(self, service: Service) -> bool:
        try:
            health = request_json(f"{service.url}health", timeout=2.0)
        except Exception:  # noqa: BLE001
            return False
        if health.get("status") != "ok" or health.get("service") != service.expected_service:
            return False
        return not service.surface or health.get("surface") == service.surface

    def start_one(self, service: Service, timeout: float = 180.0) -> dict[str, Any]:
        import uvicorn

        if port_is_open(service.port):
            if self._adoptable(service):
                self.adopted.add(service.key)
                return request_json(f"{service.url}health")
            raise RuntimeError(
                f"Порт {service.port} занят другой программой. "
                f"Освободите его или задайте IINS_PORT_OFFSET."
            )

        app = self.load_app(service)
        config = uvicorn.Config(app, host=HOST, port=service.port,
                                log_level="warning", access_log=False, log_config=None)
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name=f"I-ins-{service.key}", daemon=True)
        self.servers[service.key] = server
        self.threads[service.key] = thread
        thread.start()

        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError(f"Модуль «{service.title}» завершился при запуске. См. журнал.")
            try:
                health = request_json(f"{service.url}health", timeout=2.0)
                if health.get("status") == "ok":
                    return health
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(0.4)
        raise TimeoutError(f"Модуль «{service.title}» не запустился: {last_error}")

    def start_all(self, progress: Callable[[str, str], None] | None = None) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for service in self.services:
            if progress:
                progress(service.key, "Запуск…")
            result[service.key] = self.start_one(service)
            if progress:
                progress(service.key, "Готов")
        return result

    def stop(self) -> None:
        for server in self.servers.values():
            server.should_exit = True
        deadline = time.monotonic() + 15.0
        for thread in self.threads.values():
            thread.join(timeout=max(0.1, deadline - time.monotonic()))


# ------------------------------------------------------------------ самопроверка

REQUIRED_IMPORTS = (
    "fastapi", "uvicorn", "sqlalchemy", "pydantic", "pydantic_settings",
    "passlib", "bcrypt", "multipart", "httpx", "numpy", "pandas",
    "sklearn", "scipy", "joblib", "faker", "pypdf",
)


def check_models(runtime: Path) -> list[str]:
    """Грузит все встроенные .joblib текущей версией scikit-learn."""
    notes: list[str] = []
    import joblib
    import sklearn

    installed = sklearn.__version__
    if installed != MODEL_TRAINED_SKLEARN:
        notes.append(
            f"модели обучены scikit-learn {MODEL_TRAINED_SKLEARN}, установлена {installed} — "
            "проверяем фактическую загрузку"
        )
    models = sorted(runtime.rglob("*.joblib"))
    if not models:
        raise RuntimeError("В комплекте не найдено ни одной ML-модели (.joblib)")
    failed: list[str] = []
    for path in models:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                joblib.load(path)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{path.relative_to(runtime)}: {type(exc).__name__}: {exc}")
    if failed:
        raise RuntimeError(
            "Не загрузились ML-модели с установленной версией scikit-learn:\n  "
            + "\n  ".join(failed[:5])
            + f"\nУстановите scikit-learn=={MODEL_TRAINED_SKLEARN} и повторите запуск."
        )
    notes.append(f"загружено моделей: {len(models)}")
    return notes


def check_knowledge_base(runtime: Path) -> list[str]:
    notes: list[str] = []
    total_chunks = 0
    for service in SERVICES:
        store = runtime / "modules" / service.key / "knowledge_base" / "rag_store" / "vectors.sqlite3"
        if not store.is_file():
            raise RuntimeError(f"Нет базы знаний модуля {service.key}: {store}")
        connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=10.0)
        try:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError(f"База знаний повреждена: {store}")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            table = "chunks" if "chunks" in tables else next(iter(sorted(tables)), "")
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table else 0
        finally:
            connection.close()
        count = int(count)
        if count < service.min_chunks:
            raise RuntimeError(
                f"База знаний модуля {service.key} неполная: {count} фрагментов "
                f"вместо {service.min_chunks}"
            )
        total_chunks += count
        notes.append(f"{service.key}: фрагментов {count}")
    pdfs = len(list(runtime.rglob("*.pdf")))
    notes.append(f"всего фрагментов {total_chunks}, PDF-документов {pdfs}")
    if total_chunks < EXPECTED_TOTAL_CHUNKS or pdfs < EXPECTED_PDF_FILES:
        raise RuntimeError(
            f"База знаний неполная: фрагментов {total_chunks} из {EXPECTED_TOTAL_CHUNKS}, "
            f"PDF {pdfs} из {EXPECTED_PDF_FILES}. Переустановите комплект: --force-extract"
        )
    return notes


def run_self_check(force_extract: bool) -> int:
    root = data_root()
    log_file = setup_logging(root)
    print(f"{APP_NAME} {APP_VERSION}")
    print(f"Python:   {platform.python_version()} ({sys.executable})")
    print(f"Система:  {platform.system()} {platform.release()} / {platform.machine()}")
    print(f"Данные:   {root}")
    print(f"Журнал:   {log_file}")
    print()

    problems: list[str] = []

    if sys.version_info[:2] < (3, 11) or sys.version_info[:2] >= (3, 14):
        problems.append(f"нужен Python 3.11–3.13, найден {platform.python_version()}")

    missing = []
    for name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{name} ({type(exc).__name__})")
    if missing:
        problems.append("не установлены библиотеки: " + ", ".join(missing))
    else:
        print("[ок] Python-библиотеки на месте")

    try:
        importlib.import_module("tkinter")
        print("[ок] Tkinter доступен")
    except Exception:  # noqa: BLE001
        problems.append("в этом Python нет Tkinter — установите Python с python.org")

    if problems:
        print()
        for line in problems:
            print(f"[ошибка] {line}")
        return 1

    try:
        prepare_state(root)
        print("[ок] Рабочая папка доступна на запись")
        runtime = ensure_runtime(root, force=force_extract, progress=lambda text: print(f"      {text}"))
        origin = "используется на месте" if inplace_payload() == runtime else "установлен"
        print(f"[ок] Комплект {origin}: {runtime}")
        for note in check_models(runtime):
            print(f"      {note}")
        print("[ок] ML-модели загружаются")
        for note in check_knowledge_base(runtime):
            print(f"      {note}")
        print("[ок] База знаний полная")
        ready, note = gigachat_probe()
        print(f"[{'ок' if ready else ' —'}] GigaChat: {note}")
        print("      Qwen RAG включается сам, когда на этом Mac запущена Ollama")
    except Exception as exc:  # noqa: BLE001
        logging.exception("Самопроверка не пройдена")
        print()
        print(f"[ошибка] {type(exc).__name__}: {exc}")
        return 1

    busy = [s for s in active_services() if port_is_open(s.port)]
    if busy:
        print()
        print("[внимание] уже заняты порты: " + ", ".join(str(s.port) for s in busy))
        print("           если это работающий I-ins — всё в порядке")

    print()
    print("Самопроверка пройдена. Можно запускать I-ins.")
    return 0


# -------------------------------------------------------------------- smoke-test


def validate_service(service: Service) -> dict[str, Any]:
    health = request_json(f"{service.url}health", timeout=20.0)
    if health.get("status") != "ok":
        raise RuntimeError(f"{service.title}: health != ok")
    login = request_json(f"{service.url}api/auth/login", method="POST",
                         body={"username": service.login, "password": service.password},
                         timeout=30.0)
    token = str(login.get("access_token") or "")
    if len(token) < 20:
        raise RuntimeError(f"{service.title}: вход не выдал access_token")
    with urllib.request.urlopen(service.url, timeout=20.0) as response:
        root_ok = response.status == 200 and len(response.read(1024)) > 0
    return {"health": health, "login": "ok", "root": root_ok,
            "token_length": len(token), "token": token}


def run_smoke_test(report_path: Path | None, force_extract: bool) -> int:
    root = data_root()
    log_file = setup_logging(root)
    manager: RuntimeManager | None = None
    report: dict[str, Any] = {
        "product": APP_NAME,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "platform": sys.platform,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "modules": {},
        "status": "failed",
        "log": str(log_file),
    }
    code = 1
    try:
        manager = RuntimeManager(root, force_extract=force_extract,
                                 progress=lambda text: print(f"  {text}"))
        manager.start_all(progress=lambda key, status: print(f"  {key}: {status}"))
        for service in manager.services:
            checked = validate_service(service)
            token = checked.pop("token")
            report["modules"][service.key] = checked
            rag = request_json(f"{service.url}{service.rag_status_path}", token=token, timeout=60.0)
            chunks = int(rag.get("corpus_chunks") or 0)
            answer = request_json(
                f"{service.url}{service.rag_ask_path}", method="POST", token=token,
                body={"question": smoke_question(service.key),
                      "top_k": 4, "lang": "ru", "mode": "extractive"},
                timeout=180.0,
            )
            modes = list(rag.get("modes") or [])
            report["modules"][service.key]["rag"] = {
                "ready": bool(rag.get("ready")),
                "documents": rag.get("corpus_documents"),
                "chunks": chunks,
                "min_chunks": service.min_chunks,
                "answered": bool(answer.get("answered")),
                "sources": len(answer.get("chunks_used") or []),
                "modes": modes,
                "gigachat_ready": bool((rag.get("gigachat") or {}).get("available")),
                "qwen_ready": bool((rag.get("ollama") or {}).get("model_ready")),
            }
            for required in ("extractive", "ollama", "gigachat"):
                if required not in modes:
                    raise RuntimeError(
                        f"{service.title}: в кабинете нет режима {required}; доступны {modes}"
                    )
            # Если языковая модель заявлена готовой — проверяем, что она отвечает.
            lm_mode = ""
            if (rag.get("ollama") or {}).get("model_ready"):
                lm_mode = "ollama"
            elif (rag.get("gigachat") or {}).get("available"):
                lm_mode = "gigachat"
            if lm_mode:
                lm_answer = request_json(
                    f"{service.url}{service.rag_ask_path}", method="POST", token=token,
                    body={"question": smoke_question(service.key), "top_k": 4,
                          "lang": "ru", "mode": lm_mode},
                    timeout=240.0,
                )
                report["modules"][service.key]["lm"] = {
                    "mode": lm_answer.get("mode"),
                    "model": lm_answer.get("model"),
                    "answered": bool(lm_answer.get("answered")),
                }
                if lm_answer.get("mode") != lm_mode or not lm_answer.get("answered"):
                    raise RuntimeError(
                        f"{service.title}: режим {lm_mode} заявлен готовым, но ответа не дал"
                    )
            if not rag.get("ready"):
                raise RuntimeError(f"{service.title}: база знаний не готова: {rag}")
            if chunks < service.min_chunks:
                raise RuntimeError(
                    f"{service.title}: неполная база знаний — {chunks} фрагментов, "
                    f"ожидалось не меньше {service.min_chunks}"
                )
            if not answer.get("answered") or not answer.get("chunks_used"):
                raise RuntimeError(f"{service.title}: RAG не вернул подтверждённый ответ")
        report["status"] = "passed"
        code = 0
    except Exception as exc:  # noqa: BLE001
        logging.exception("Smoke-test не пройден")
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[ошибка] {type(exc).__name__}: {exc}")
    finally:
        if manager is not None:
            manager.stop()
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        destination = report_path or (root / "logs" / "smoke-test.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Отчёт: {destination}")
    return code


# -------------------------------------------------------------------------- окно


class LauncherWindow:
    def __init__(self, force_extract: bool = False) -> None:
        import queue
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.messagebox = messagebox
        self.queue: Any = queue.Queue()
        self.root_data = data_root()
        self.log_file = setup_logging(self.root_data)
        self.manager: RuntimeManager | None = None
        self.services = active_services()
        self.force_extract = force_extract
        self.closing = False

        window = tk.Tk()
        self.window = window
        window.title(f"{APP_NAME} · цифровой помощник страховой и юридической компании")
        window.geometry("820x620")
        window.minsize(760, 560)
        window.configure(bg="#f4f7fb")
        window.protocol("WM_DELETE_WINDOW", self.close)

        family = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
        style = ttk.Style(window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=(family, 24, "bold"), foreground="#12355b", background="#f4f7fb")
        style.configure("Sub.TLabel", font=(family, 11), foreground="#4a6078", background="#f4f7fb")
        style.configure("Module.TButton", font=(family, 11, "bold"), padding=(14, 9))
        style.configure("Status.TLabel", font=(family, 10), background="#ffffff")

        header = ttk.Frame(window, padding=(26, 20, 26, 8))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=f"Шесть кабинетов работают локально · версия {APP_VERSION}",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))

        content = tk.Frame(window, bg="#ffffff", highlightbackground="#d9e2ef", highlightthickness=1)
        content.pack(fill="both", expand=True, padx=26, pady=10)
        content.grid_columnconfigure(0, weight=1)
        self.status_labels: dict[str, Any] = {}
        self.buttons: dict[str, Any] = {}

        for row, service in enumerate(self.services):
            frame = tk.Frame(content, bg="#ffffff", padx=14, pady=8)
            frame.grid(row=row, column=0, sticky="ew")
            frame.grid_columnconfigure(0, weight=1)
            tk.Label(frame, text=service.title, bg="#ffffff", fg="#17324d",
                     font=(family, 12, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
            tk.Label(frame, text=service.description, bg="#ffffff", fg="#5d7186",
                     font=(family, 10), anchor="w").grid(row=1, column=0, sticky="w")
            tk.Label(frame, text=f"{service.url}   ·   {service.login} / {service.password}",
                     bg="#ffffff", fg="#8496a8", font=(family, 9)).grid(row=2, column=0, sticky="w", pady=(1, 0))
            status = ttk.Label(frame, text="Ожидание", style="Status.TLabel", foreground="#7b8794")
            status.grid(row=0, column=1, rowspan=3, padx=14)
            button = ttk.Button(frame, text="Открыть", style="Module.TButton",
                                command=lambda url=service.url: webbrowser.open(url))
            button.grid(row=0, column=2, rowspan=3)
            button.state(["disabled"])
            self.status_labels[service.key] = status
            self.buttons[service.key] = button
            if row < len(self.services) - 1:
                tk.Frame(content, bg="#e7edf5", height=1).grid(row=row, column=0, sticky="sew")

        footer = ttk.Frame(window, padding=(26, 4, 26, 16))
        footer.pack(fill="x")
        self.summary = ttk.Label(footer, text="Подготовка локальной среды…", style="Sub.TLabel")
        self.summary.pack(side="left")
        ttk.Button(footer, text="Журнал", command=lambda: self.reveal(self.log_file)).pack(side="right")
        ttk.Button(footer, text="Папка данных", command=lambda: self.reveal(self.root_data)).pack(side="right", padx=(0, 8))

        threading.Thread(target=self.worker, name="I-ins-bootstrap", daemon=True).start()
        window.after(120, self.poll)

    def reveal(self, path: Path) -> None:
        import subprocess
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def worker(self) -> None:
        try:
            self.manager = RuntimeManager(
                self.root_data,
                force_extract=self.force_extract,
                progress=lambda text: self.queue.put(("summary", text)),
            )
            self.manager.start_all(progress=lambda key, status: self.queue.put(("progress", key, status)))
            self.queue.put(("ready",))
        except Exception as exc:  # noqa: BLE001
            logging.exception("Запуск не удался")
            self.queue.put(("error", f"{type(exc).__name__}: {exc}"))

    def poll(self) -> None:
        if self.closing:
            return
        while True:
            try:
                event = self.queue.get_nowait()
            except Exception:  # noqa: BLE001  (queue.Empty)
                break
            try:
                self.handle(event)
            except Exception:  # noqa: BLE001
                logging.exception("Ошибка обработки события интерфейса")
        self.window.after(120, self.poll)

    def handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "summary":
            self.summary.configure(text=event[1])
        elif kind == "progress":
            _, key, status = event
            self.status_labels[key].configure(
                text=status, foreground="#1f8a5b" if status == "Готов" else "#d08318")
            if status == "Готов":
                self.buttons[key].state(["!disabled"])
        elif kind == "ready":
            self.summary.configure(text="Все шесть модулей готовы к работе")
            webbrowser.open(self.services[0].url)
        elif kind == "error":
            self.summary.configure(text="Не удалось запустить весь комплект")
            self.messagebox.showerror(APP_NAME, f"{event[1]}\n\nПодробности: {self.log_file}")

    def close(self) -> None:
        self.closing = True
        if self.manager is not None:
            self.summary.configure(text="Остановка модулей…")
            self.window.update_idletasks()
            self.manager.stop()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()


# -------------------------------------------------------------------------- CLI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="iins_runtime", description=f"{APP_NAME} — локальный запуск")
    parser.add_argument("--self-check", action="store_true", help="проверить окружение и комплект")
    parser.add_argument("--smoke-test", action="store_true", help="запустить и проверить все модули без окна")
    parser.add_argument("--report", type=Path, help="куда сохранить JSON-отчёт smoke-теста")
    parser.add_argument("--force-extract", action="store_true", help="переустановить payload заново")
    parser.add_argument("--version", action="store_true", help="показать версию")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if args.self_check:
        return run_self_check(args.force_extract)
    if args.smoke_test:
        return run_smoke_test(args.report, args.force_extract)
    LauncherWindow(force_extract=args.force_extract).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
