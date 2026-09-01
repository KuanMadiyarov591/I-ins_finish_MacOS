#!/bin/bash
# I-ins для macOS — установка окружения и запуск шести кабинетов.
# Двойной щелчок по этому файлу делает всё необходимое.
# Работает одинаково на Apple Silicon и на Intel.

set -u

APP_NAME="I-ins"
APP_VERSION="1.2.0-macos"
MIN_PY="3.11"
MAX_PY="3.13"

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_SRC="$SOURCE_DIR/runtime"
# Куда ставить окружение Python и рабочие данные.
# На учебных Mac домашняя квота мала, а локальный диск смонтирован как
# ~/goinfre — при его наличии ставим туда. Переопределяется IINS_HOME.
if [[ -n "${IINS_HOME:-}" ]]; then
  APP_HOME="$IINS_HOME"
elif [[ -d "$HOME/goinfre" ]]; then
  APP_HOME="$HOME/goinfre/$APP_NAME"
else
  APP_HOME="$HOME/Library/Application Support/$APP_NAME"
fi
export IINS_DATA_ROOT="$APP_HOME"
VENV_DIR="$APP_HOME/venv-$APP_VERSION"
LOG_DIR="$APP_HOME/logs"
BOOTSTRAP_LOG="$LOG_DIR/bootstrap.log"
DEPS_MARKER="$VENV_DIR/.dependencies-ready"

mkdir -p "$LOG_DIR"
: > /dev/null
exec > >(tee -a "$BOOTSTRAP_LOG") 2>&1

echo
echo "============================================================"
echo " $APP_NAME $APP_VERSION — подготовка окружения macOS"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
echo

fail() {
  echo
  echo "ОШИБКА: $1"
  /usr/bin/osascript -e "display dialog \"$1\" with title \"$APP_NAME\" buttons {\"OK\"} default button \"OK\" with icon stop" >/dev/null 2>&1 || true
  echo
  echo "Полный журнал: $BOOTSTRAP_LOG"
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _
  exit 1
}

# --- 1. Комплект на месте ---------------------------------------------------
if [[ ! -f "$RUNTIME_SRC/iins_runtime.py" ]]; then
  fail "Файлы программы неполные. Распакуйте архив $APP_NAME целиком и не перемещайте содержимое папки runtime."
fi
if [[ ! -f "$RUNTIME_SRC/payload.zip" && ! -d "$SOURCE_DIR/payload/modules" ]]; then
  fail "Не найден комплект: нет ни runtime/payload.zip, ни папки payload/modules."
fi

# macOS помечает скачанные файлы карантином — снимаем метку со своей папки.
/usr/bin/xattr -dr com.apple.quarantine "$SOURCE_DIR" >/dev/null 2>&1 || true
chmod +x "$SOURCE_DIR"/*.command >/dev/null 2>&1 || true

echo "Папка программы: $SOURCE_DIR"
echo "Папка данных:    $APP_HOME"
echo "Архитектура:     $(uname -m)"
echo "macOS:           $(sw_vers -productVersion 2>/dev/null || echo неизвестно)"
echo

# --- 1a. Свободное место ----------------------------------------------------
# Окружению Python нужно около 1.5 ГБ. Комплект вторую копию не занимает:
# он используется прямо из папки payload.
NEED_MB=2048
SPACE_DIR="$APP_HOME"
while [[ ! -d "$SPACE_DIR" && "$SPACE_DIR" != "/" ]]; do SPACE_DIR="$(dirname "$SPACE_DIR")"; done
FREE_MB="$(df -m "$SPACE_DIR" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ -n "${FREE_MB:-}" && "$FREE_MB" =~ ^[0-9]+$ ]]; then
  echo "Установка в: $APP_HOME"
  echo "Свободно там: ${FREE_MB} МБ (нужно не меньше ${NEED_MB} МБ)"
  if (( FREE_MB < NEED_MB )); then
    fail "Мало места на диске: свободно ${FREE_MB} МБ, нужно не меньше ${NEED_MB} МБ. Освободите место и запустите снова."
  fi
  echo
fi

# --- 2. Подходящий Python ---------------------------------------------------
python_ok() {
  local bin="$1"
  [[ -n "$bin" && -x "$bin" ]] || return 1
  "$bin" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1 || return 1
  "$bin" -c 'import tkinter' >/dev/null 2>&1 || return 1
  return 0
}

find_python() {
  local candidate
  local candidates=(
    "${IINS_PYTHON:-}"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "$(command -v python3 2>/dev/null || true)"
  )
  for candidate in "${candidates[@]}"; do
    if python_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  /usr/bin/open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
  fail "Нужен Python $MIN_PY–$MAX_PY с Tkinter. Установите Python для macOS с сайта python.org (обычный установщик, universal2), затем снова откройте $APP_NAME.command."
fi

echo "Python: $PYTHON_BIN"
"$PYTHON_BIN" --version
echo

# --- 3. Виртуальное окружение ----------------------------------------------
if [[ -x "$VENV_DIR/bin/python" ]]; then
  if ! "$VENV_DIR/bin/python" -c 'import sys,tkinter; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<(3,14) else 1)' >/dev/null 2>&1; then
    echo "Окружение устарело или повреждено — пересоздаётся."
    rm -rf "$VENV_DIR"
  fi
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Создание изолированного окружения Python…"
  mkdir -p "$APP_HOME"
  "$PYTHON_BIN" -m venv "$VENV_DIR" || fail "Не удалось создать виртуальное окружение в $VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"

# --- 4. Библиотеки ----------------------------------------------------------
if [[ ! -f "$DEPS_MARKER" || "$SOURCE_DIR/requirements-macos.txt" -nt "$DEPS_MARKER" ]]; then
  echo "Установка библиотек. При первом запуске это занимает 5–15 минут."
  echo "Нужен интернет. Повторно этот шаг не выполняется."
  echo
  "$VENV_PY" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel \
    || fail "Не удалось обновить pip. Проверьте интернет и прокси."

  if ! "$VENV_PY" -m pip install --disable-pip-version-check --prefer-binary \
       -r "$SOURCE_DIR/requirements-macos.txt"; then
    echo
    echo "Точная версия scikit-learn недоступна для этой связки Python и архитектуры."
    echo "Повторная попытка с ближайшей совместимой версией…"
    TMP_REQ="$(mktemp "${TMPDIR:-/tmp}/iins-req.XXXXXX")"
    sed 's/^scikit-learn==1\.9\.0$/scikit-learn>=1.6,<2/' "$SOURCE_DIR/requirements-macos.txt" > "$TMP_REQ"
    "$VENV_PY" -m pip install --disable-pip-version-check --prefer-binary -r "$TMP_REQ" \
      || { rm -f "$TMP_REQ"; fail "Не удалось установить библиотеки. Смотрите журнал: $BOOTSTRAP_LOG"; }
    rm -f "$TMP_REQ"
    echo
    echo "Внимание: версия scikit-learn отличается от той, которой обучены модели."
    echo "Самопроверка ниже реально загрузит все модели и покажет, работают ли они."
  fi
  printf '%s\n' "$APP_VERSION" > "$DEPS_MARKER"
  echo
  echo "Библиотеки установлены."
  echo
fi

# --- 4a. Ключ GigaChat ------------------------------------------------------
# Спрашивается ровно один раз. Дальше лежит в папке данных и переживает
# обновление программы: в самом комплекте и в репозитории ключа нет.
KEY_FILE="$APP_HOME/gigachat.key"
GIGACHAT_URL="${GIGACHAT_BASE_URL:-https://gigachat-students.nsk.21-school.ru/v1}"

giga_probe() {
  local code
  code="$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
          -H "Authorization: Bearer $1" "$GIGACHAT_URL/models" 2>/dev/null || echo 000)"
  case "$code" in
    2*|404|405) return 0 ;;   # сервис отвечает
    401|403)    return 2 ;;   # ключ отклонён
    *)          return 3 ;;   # нет связи
  esac
}

giga_save() {
  mkdir -p "$APP_HOME"
  printf '%s\n' "$1" > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
}

if [[ -z "${GIGACHAT_API_KEY:-}" ]]; then
  for candidate in "$SOURCE_DIR/gigachat.key" "$KEY_FILE"; do
    if [[ -f "$candidate" ]]; then
      GIGACHAT_API_KEY="$(tr -d '[:space:]' < "$candidate")"
      [[ -n "$GIGACHAT_API_KEY" ]] && break
    fi
  done
fi

if [[ -z "${GIGACHAT_API_KEY:-}" && -t 0 ]]; then
  echo "------------------------------------------------------------"
  echo " Ключ GigaChat"
  echo
  echo " Спрашивается один раз. Дальше он хранится в"
  echo "   $KEY_FILE"
  echo " и больше не запрашивается — ни при запуске, ни после обновления."
  echo
  echo " Enter без ввода — работать без GigaChat: режимы «по базе знаний»"
  echo " и «Qwen RAG» ключа не требуют."
  echo "------------------------------------------------------------"
  for attempt in 1 2 3; do
    printf 'Ключ GigaChat (ввод скрыт): '
    read -r -s entered || entered=""
    echo
    entered="$(printf '%s' "$entered" | tr -d '[:space:]')"
    if [[ -z "$entered" ]]; then
      echo "Пропущено. Позже ключ можно задать так:"
      echo "  echo 'sk-…' > \"$KEY_FILE\""
      break
    fi
    echo "Проверка ключа на $GIGACHAT_URL …"
    giga_probe "$entered"
    case $? in
      0) giga_save "$entered"; GIGACHAT_API_KEY="$entered"
         echo "Ключ принят и сохранён."; break ;;
      2) echo "Сервис отклонил этот ключ."
         [[ $attempt -lt 3 ]] && echo "Попробуйте ещё раз." || echo "Продолжаю без GigaChat." ;;
      *) giga_save "$entered"; GIGACHAT_API_KEY="$entered"
         echo "Сервис сейчас недоступен, ключ сохранён — он подхватится, когда появится связь."
         break ;;
    esac
  done
  echo
fi
export GIGACHAT_API_KEY="${GIGACHAT_API_KEY:-}"

# --- 5. Самопроверка --------------------------------------------------------
export PYTHONDONTWRITEBYTECODE="1"
export PYTHONUTF8="1"

echo "Проверка комплекта, моделей и базы знаний…"
echo "Комплект берётся из папки payload — вторая копия на диск не пишется."
echo
if ! "$VENV_PY" "$RUNTIME_SRC/iins_runtime.py" --self-check; then
  fail "Самопроверка $APP_NAME не пройдена. Подробности в журнале: $BOOTSTRAP_LOG"
fi

if [[ "${1:-}" == "--check-only" ]]; then
  echo
  echo "ПРОВЕРКА ЗАВЕРШЕНА: $APP_NAME готов к запуску."
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _
  exit 0
fi

if [[ "${1:-}" == "--smoke-test" ]]; then
  echo
  echo "Полный smoke-test всех шести модулей…"
  IINS_PORT_OFFSET="${IINS_PORT_OFFSET:-12000}" \
    "$VENV_PY" "$RUNTIME_SRC/iins_runtime.py" --smoke-test --report "$LOG_DIR/smoke-test.json"
  code=$?
  echo
  [[ $code -eq 0 ]] && echo "SMOKE-TEST ПРОЙДЕН." || echo "SMOKE-TEST НЕ ПРОЙДЕН (код $code)."
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _
  exit $code
fi

# --- 6. Запуск --------------------------------------------------------------
echo
echo "Запуск общего окна $APP_NAME."
echo "Закрытие окна корректно останавливает все шесть модулей."
echo
exec "$VENV_PY" "$RUNTIME_SRC/iins_runtime.py"
