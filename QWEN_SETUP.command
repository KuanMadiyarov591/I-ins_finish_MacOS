#!/bin/bash
# Проверка и настройка локального Qwen для I-ins.
#
# Кабинеты I-ins отвечают двумя способами: по базе знаний (работает всегда)
# и через локальную модель Qwen. Второй способ требует запущенной Ollama
# и скачанной модели. Этот скрипт проверяет обе вещи и, если чего-то
# не хватает, доводит до рабочего состояния.
#
# Запуск: двойной щелчок по файлу или ./QWEN_SETUP.command

set -uo pipefail

BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
WANT_MODEL="${OLLAMA_MODEL:-qwen2.5:1.5b}"
PORT="${BASE_URL##*:}"
PORT="${PORT%%/*}"

say()  { printf '%s\n' "$*"; }
ok()   { printf '[ок] %s\n' "$*"; }
bad()  { printf '[ — ] %s\n' "$*"; }
head_() { printf '\n%s\n' "$*"; printf '%s\n' "------------------------------------------------------------"; }
finish() {
  say
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true
  exit "${1:-0}"
}

cd "$(dirname "$0")" 2>/dev/null || true

say "============================================================"
say " I-ins — локальный Qwen: проверка и настройка"
say "============================================================"
say "Адрес Ollama : $BASE_URL"
say "Модель       : $WANT_MODEL"

# --- 1. Где лежит ollama ----------------------------------------------------
head_ "1. Программа Ollama"

OLLAMA=""
for candidate in \
  "$(command -v ollama 2>/dev/null || true)" \
  /opt/homebrew/bin/ollama \
  /usr/local/bin/ollama \
  /Applications/Ollama.app/Contents/Resources/ollama \
  "$HOME/goinfre/ollama/ollama" \
  "$HOME/.local/bin/ollama"
do
  if [[ -n "$candidate" && -x "$candidate" ]]; then OLLAMA="$candidate"; break; fi
done

if [[ -z "$OLLAMA" ]]; then
  bad "Ollama на этом Mac не найдена."
  say
  say "Поставьте одним из способов и запустите этот файл заново:"
  say
  say "  Homebrew:      brew install ollama"
  say "  Готовое приложение: https://ollama.com/download  (файл Ollama-darwin.zip,"
  say "                      распакуйте и перетащите Ollama.app в Программы)"
  say
  say "Без Qwen кабинеты продолжают работать: режим «RAG по базе знаний»"
  say "отвечает по документам и модели не требует."
  finish 1
fi
ok "Найдена: $OLLAMA"

# --- 2. Куда складывать модели ---------------------------------------------
head_ "2. Место под модель"

if [[ -z "${OLLAMA_MODELS:-}" && -d "$HOME/goinfre" ]]; then
  # На учебных Mac домашняя квота мала, а goinfre — локальный диск.
  # Модель весит около гигабайта, в домашнюю папку она часто не влезает.
  export OLLAMA_MODELS="$HOME/goinfre/ollama-models"
  mkdir -p "$OLLAMA_MODELS"
  ok "Учебный Mac: модели пойдут в $OLLAMA_MODELS"
elif [[ -n "${OLLAMA_MODELS:-}" ]]; then
  mkdir -p "$OLLAMA_MODELS"
  ok "Модели пойдут в $OLLAMA_MODELS (задано переменной OLLAMA_MODELS)"
else
  ok "Модели пойдут в $HOME/.ollama/models (место по умолчанию)"
fi

FREE="$(df -h "${OLLAMA_MODELS:-$HOME}" 2>/dev/null | tail -1 | awk '{print $4}')"
say "     свободно на этом разделе: ${FREE:-неизвестно} (модели нужно около 1 ГБ)"

# --- 3. Запущен ли сервер ---------------------------------------------------
head_ "3. Сервер Ollama"

port_open() {
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1
  else
    curl -fsS -m 3 -o /dev/null "$BASE_URL/api/tags" >/dev/null 2>&1
  fi
}

if port_open; then
  ok "Уже слушает порт $PORT"
else
  say "Не отвечает — запускаю…"
  LOG="${TMPDIR:-/tmp}/iins-ollama.log"
  nohup "$OLLAMA" serve > "$LOG" 2>&1 &
  for _ in $(seq 1 30); do
    sleep 1
    port_open && break
  done
  if port_open; then
    ok "Запущен, журнал: $LOG"
  else
    bad "Запустить не удалось. Посмотрите журнал: $LOG"
    say
    say "Часто помогает запустить вручную в отдельном окне Терминала:"
    say "  $OLLAMA serve"
    finish 1
  fi
fi

# --- 4. Какие модели скачаны ------------------------------------------------
head_ "4. Модели"

tags_json() { curl -fsS -m 10 "$BASE_URL/api/tags" 2>/dev/null; }

# Разбор ответа без Python: на учебных Mac его версия может быть любой.
model_names() {
  tags_json | tr ',' '\n' \
    | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}

# Та же логика выбора, что и в кабинетах: точный тег, иначе то же
# семейство, иначе любая модель Qwen.
qwen_present() {
  local names fam fam_esc hit
  names="$(model_names)"
  [[ -z "$names" ]] && return 1
  hit="$(printf '%s\n' "$names" | grep -Fx -- "$WANT_MODEL" | head -1)"
  if [[ -z "$hit" ]]; then
    fam="${WANT_MODEL%%:*}"
    fam_esc="$(printf '%s' "$fam" | sed 's/[].[^$*\\/]/\\&/g')"
    hit="$(printf '%s\n' "$names" | grep -i -- "^${fam_esc}:" | sort | head -1)"
  fi
  if [[ -z "$hit" ]]; then
    hit="$(printf '%s\n' "$names" | grep -i -- '^qwen' | sort | head -1)"
  fi
  [[ -z "$hit" ]] && return 1
  printf '%s' "$hit"
}

CHOSEN="$(qwen_present || true)"
if [[ -n "$CHOSEN" ]]; then
  ok "Модель Qwen на месте: $CHOSEN"
  [[ "$CHOSEN" != "$WANT_MODEL" ]] && say "     кабинеты возьмут её вместо $WANT_MODEL — это нормально"
else
  ALL="$(model_names | paste -sd, - | sed 's/,/, /g')"
  [[ -z "$ALL" ]] && ALL="их нет"
  bad "Моделей Qwen нет (сейчас скачано: $ALL)"
  say
  say "Скачиваю $WANT_MODEL — это около 1 ГБ, займёт несколько минут."
  say
  if "$OLLAMA" pull "$WANT_MODEL"; then
    CHOSEN="$(qwen_present || true)"
    [[ -n "$CHOSEN" ]] && ok "Скачана: $CHOSEN" || bad "Скачать не удалось"
  else
    bad "Скачать не удалось — проверьте связь и свободное место"
    finish 1
  fi
fi

# --- 5. Итог ----------------------------------------------------------------
head_ "Итог"

if [[ -n "$CHOSEN" ]]; then
  ok "Qwen готов. Модель: $CHOSEN"
  say
  say "Теперь запустите ./I-ins.command — в кабинетах станут доступны"
  say "режимы «Авто» и «Qwen RAG»; переключатель перестанет быть серым."
  say
  say "Если страница уже открыта, обновите её в браузере: кабинеты"
  say "проверяют Ollama при каждом обновлении состояния."
  if [[ -n "${OLLAMA_MODELS:-}" ]]; then
    say
    say "Важно: модели лежат в $OLLAMA_MODELS."
    say "После перезагрузки Mac запустите этот файл ещё раз — он поднимет"
    say "сервер с той же папкой моделей. Если запускать Ollama самому,"
    say "переменную нужно задать: export OLLAMA_MODELS=\"$OLLAMA_MODELS\""
  fi
  finish 0
fi

bad "Qwen поднять не удалось."
say "Кабинеты продолжат работать в режиме «RAG по базе знаний»."
finish 1
