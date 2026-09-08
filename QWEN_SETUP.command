#!/bin/bash
# Проверка и настройка локального Qwen для I-ins.
#
# Кабинеты I-ins отвечают двумя способами: по базе знаний (работает всегда)
# и через локальную модель Qwen. Второй способ требует, чтобы на этом Mac
# отвечал сервер Ollama и была скачана модель.
#
# Кабинеты общаются с Ollama только по HTTP и о том, где лежит программа,
# ничего не знают. Поэтому и здесь проверка идёт по HTTP: сначала стучимся
# на порт, и только если никто не ответил, ищем программу, чтобы её запустить.
#
# Запуск: двойной щелчок по файлу или ./QWEN_SETUP.command

set -uo pipefail

BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
WANT_MODEL="${OLLAMA_MODEL:-qwen2.5:1.5b}"
PORT="${BASE_URL##*:}"
PORT="${PORT%%/*}"
TRIED=""

say()   { printf '%s\n' "$*"; }
ok()    { printf '[ок] %s\n' "$*"; }
bad()   { printf '[ — ] %s\n' "$*"; }
head_() { printf '\n%s\n------------------------------------------------------------\n' "$*"; }
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

tags_json() { curl -fsS -m 10 "$BASE_URL/api/tags" 2>/dev/null; }
server_up()  { curl -fsS -m 5 -o /dev/null "$BASE_URL/api/tags" >/dev/null 2>&1; }

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

# --- 1. Отвечает ли сервер --------------------------------------------------
head_ "1. Сервер Ollama"

OLLAMA=""
if server_up; then
  ok "Отвечает на $BASE_URL — программу искать не нужно"
else
  say "На $BASE_URL никто не отвечает. Ищу программу, чтобы запустить…"
  say

  # PATH текущей оболочки. При двойном щелчке из Finder он куцый и профиль
  # пользователя не читается, поэтому дальше спрашиваем ещё и login-оболочку.
  add_try() { TRIED="$TRIED  $1"$'\n'; }

  cand="$(command -v ollama 2>/dev/null || true)"
  add_try "PATH этой оболочки: ${cand:-не найдено}"
  [[ -n "$cand" && -x "$cand" ]] && OLLAMA="$cand"

  if [[ -z "$OLLAMA" ]]; then
    # PATH из вашего профиля: именно там ollama, если её видит Терминал.
    seen_sh=""
    for sh in "${SHELL:-/bin/zsh}" /bin/zsh /bin/bash; do
      [[ -x "$sh" ]] || continue
      case "$seen_sh" in *"|$sh|"*) continue ;; esac
      seen_sh="$seen_sh|$sh|"
      cand="$("$sh" -lc 'command -v ollama' 2>/dev/null | tail -1)"
      add_try "PATH из $sh: ${cand:-не найдено}"
      if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; break; fi
    done
  fi

  if [[ -z "$OLLAMA" ]]; then
    for cand in \
      /opt/homebrew/bin/ollama \
      /usr/local/bin/ollama \
      "$HOME/.local/bin/ollama" \
      "$HOME/bin/ollama" \
      "$HOME/goinfre/ollama/ollama" \
      "$HOME/goinfre/homebrew/bin/ollama" \
      "$HOME/goinfre/.brew/bin/ollama" \
      "$HOME/homebrew/bin/ollama" \
      "$HOME/.brew/bin/ollama" \
      "$HOME/.linuxbrew/bin/ollama" \
      /Applications/Ollama.app/Contents/Resources/ollama \
      /Applications/Ollama.app/Contents/MacOS/ollama \
      "$HOME/Applications/Ollama.app/Contents/Resources/ollama" \
      "$HOME/Applications/Ollama.app/Contents/MacOS/ollama"
    do
      if [[ -x "$cand" ]]; then OLLAMA="$cand"; add_try "по известному пути: $cand"; break; fi
    done
    [[ -z "$OLLAMA" ]] && add_try "по известным путям: не найдено"
  fi

  if [[ -z "$OLLAMA" ]]; then
    # Последняя попытка: поиск по диску Spotlight'ом и обходом папок программ.
    cand="$(mdfind -name 'Ollama.app' 2>/dev/null | head -1)"
    if [[ -n "$cand" ]]; then
      for sub in Contents/Resources/ollama Contents/MacOS/ollama; do
        [[ -x "$cand/$sub" ]] && { OLLAMA="$cand/$sub"; break; }
      done
      add_try "Spotlight нашёл: $cand"
    else
      add_try "Spotlight: Ollama.app не найден"
    fi
  fi

  if [[ -n "$OLLAMA" ]]; then
    ok "Программа найдена: $OLLAMA"
    say "Запускаю сервер…"
    LOG="${TMPDIR:-/tmp}/iins-ollama.log"
    nohup "$OLLAMA" serve > "$LOG" 2>&1 &
    for _ in $(seq 1 30); do sleep 1; server_up && break; done
  elif [[ -d /Applications/Ollama.app || -d "$HOME/Applications/Ollama.app" ]]; then
    ok "Найдено приложение Ollama.app — открываю его"
    open -a Ollama >/dev/null 2>&1
    for _ in $(seq 1 30); do sleep 1; server_up && break; done
  fi

  if server_up; then
    ok "Сервер поднялся"
  else
    bad "Сервер не отвечает."
    say
    say "Где я искал программу:"
    printf '%s' "$TRIED"
    say
    say "Самый надёжный способ — запустить сервер вручную. Откройте Терминал"
    say "и оставьте в нём выполняться:"
    say
    say "    ollama serve"
    say
    say "Затем, не закрывая то окно, запустите этот файл ещё раз."
    say
    say "Если Ollama установлена как программа, достаточно открыть Ollama"
    say "из папки «Программы» — она поднимает сервер сама."
    say
    say "Без Qwen кабинеты работают: режим «RAG по базе знаний» отвечает"
    say "по документам и модели не требует."
    finish 1
  fi
fi

# --- 2. Куда складывать модели ---------------------------------------------
head_ "2. Место под модель"

MODELS_DIR="${OLLAMA_MODELS:-}"
if [[ -z "$MODELS_DIR" && -d "$HOME/goinfre" ]]; then
  # На учебных Mac домашняя квота мала, а goinfre — локальный диск.
  # Модель весит около гигабайта, в домашнюю папку она часто не влезает.
  MODELS_DIR="$HOME/goinfre/ollama-models"
fi
if [[ -n "$MODELS_DIR" ]]; then
  mkdir -p "$MODELS_DIR" 2>/dev/null
  say "Предпочтительная папка моделей: $MODELS_DIR"
  say "     (сервер уже запущен и использует ту папку, с которой стартовал;"
  say "      если места не хватит, остановите его и запустите так:"
  say "      OLLAMA_MODELS=\"$MODELS_DIR\" ollama serve )"
else
  say "Папка моделей по умолчанию: $HOME/.ollama/models"
fi
FREE="$(df -h "${MODELS_DIR:-$HOME}" 2>/dev/null | tail -1 | awk '{print $4}')"
say "     свободно на этом разделе: ${FREE:-неизвестно} (модели нужно около 1 ГБ)"

# --- 3. Какие модели скачаны ------------------------------------------------
head_ "3. Модели"

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

  pulled=1
  if [[ -n "$OLLAMA" ]]; then
    "$OLLAMA" pull "$WANT_MODEL" && pulled=0
  else
    # Программы под рукой нет, но сервер отвечает — качаем через его же API.
    say "Программу не нашёл, качаю через сам сервер…"
    curl -fsS -m 3600 -X POST "$BASE_URL/api/pull" \
         -H 'Content-Type: application/json' \
         -d "{\"model\":\"$WANT_MODEL\",\"stream\":true}" \
      | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/  \1/p' \
      | awk '!seen[$0]++'
    pulled=$?
  fi

  if [[ $pulled -eq 0 ]]; then
    CHOSEN="$(qwen_present || true)"
    if [[ -n "$CHOSEN" ]]; then ok "Скачана: $CHOSEN"; else bad "Скачалось, но модель не видна"; fi
  else
    bad "Скачать не удалось — проверьте связь и свободное место"
    say "Вручную: ollama pull $WANT_MODEL"
    finish 1
  fi
fi

# --- 4. Итог ----------------------------------------------------------------
head_ "Итог"

if [[ -n "$CHOSEN" ]]; then
  ok "Qwen готов. Модель: $CHOSEN"
  say
  say "Теперь запустите ./I-ins.command — в кабинетах станут доступны"
  say "режимы «Авто» и «Qwen RAG»; переключатель перестанет быть серым."
  say
  say "Если страница уже открыта, обновите её в браузере: кабинеты"
  say "проверяют Ollama при каждом обновлении состояния."
  say
  say "Сервер Ollama должен оставаться запущенным всё время работы I-ins."
  finish 0
fi

bad "Qwen поднять не удалось."
say "Кабинеты продолжат работать в режиме «RAG по базе знаний»."
finish 1
