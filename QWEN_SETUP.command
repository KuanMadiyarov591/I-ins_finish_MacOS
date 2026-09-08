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

# --auto — вызов из I-ins.command: без паузы в конце и без кода ошибки,
# потому что отсутствие Qwen работу кабинетов не останавливает.
AUTO=0
[[ "${1:-}" == "--auto" || "${1:-}" == "--quiet" ]] && AUTO=1

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
  local code="${1:-0}"
  if [[ $AUTO -eq 1 ]]; then
    exit 0
  fi
  say
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _ || true
  exit "$code"
}

cd "$(dirname "$0")" 2>/dev/null || true

if [[ $AUTO -eq 1 ]]; then
  say "Локальный Qwen: проверка ($BASE_URL, модель $WANT_MODEL)"
else
  say "============================================================"
  say " I-ins — локальный Qwen: проверка и настройка"
  say "============================================================"
  say "Адрес Ollama : $BASE_URL"
  say "Модель       : $WANT_MODEL"
fi

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
add_try() { TRIED="$TRIED  $1"$'\n'; }

find_ollama() {
  local cand sh seen_sh sub app rc

  # 1. PATH текущей оболочки.
  cand="$(command -v ollama 2>/dev/null || true)"
  add_try "PATH этой оболочки: ${cand:-не найдено}"
  if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

  # 2. Псевдоним из ~/.zshrc. Очень частый случай: программа лежит там, где
  #    есть место, а в профиле на неё сделан alias. Псевдонимы живут только
  #    в интерактивной оболочке, поэтому обычный `command -v` их не видит.
  if [[ -x /bin/zsh ]]; then
    cand="$(/bin/zsh -ic 'whence -p ollama' 2>/dev/null | tail -1)"
    add_try "интерактивный zsh, обычный путь: ${cand:-не найдено}"
    if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

    cand="$(/bin/zsh -ic 'alias ollama' 2>/dev/null | tail -1 \
            | sed -e 's/^ollama=//' -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//')"
    add_try "псевдоним ollama: ${cand:-не найдено}"
    if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi
  fi

  # 3. Профили: вдруг оболочка не отвечает, а строка в файле есть.
  cand="$(grep -h "alias[[:space:]]\+ollama=" \
            "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.bash_profile" \
            2>/dev/null | tail -1 \
          | sed -e 's/.*alias[[:space:]]*ollama=//' -e "s/^'//" -e "s/'.*$//" \
                -e 's/^"//' -e 's/".*$//' -e 's/[[:space:]].*$//')"
  cand="${cand/#\~/$HOME}"
  add_try "псевдоним из профиля: ${cand:-не найдено}"
  if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

  # 4. Известные места. goinfre идёт первым: на учебных Mac программу ставят
  #    именно туда, потому что в домашней папке нет места.
  for cand in \
    "$HOME/goinfre/Ollama.app/Contents/MacOS/ollama" \
    "$HOME/goinfre/Ollama.app/Contents/Resources/ollama" \
    "$HOME/goinfre/ollama/ollama" \
    "$HOME/goinfre/homebrew/bin/ollama" \
    "$HOME/goinfre/.brew/bin/ollama" \
    /opt/homebrew/bin/ollama \
    /usr/local/bin/ollama \
    "$HOME/.local/bin/ollama" \
    "$HOME/bin/ollama" \
    "$HOME/homebrew/bin/ollama" \
    "$HOME/.brew/bin/ollama" \
    /Applications/Ollama.app/Contents/MacOS/ollama \
    /Applications/Ollama.app/Contents/Resources/ollama \
    "$HOME/Applications/Ollama.app/Contents/MacOS/ollama" \
    "$HOME/Applications/Ollama.app/Contents/Resources/ollama"
  do
    if [[ -x "$cand" ]]; then OLLAMA="$cand"; add_try "по известному пути: $cand"; return 0; fi
  done
  add_try "по известным путям: не найдено"

  # 5. Обход папок, где вообще может лежать Ollama.app.
  for app in "$HOME"/goinfre/Ollama.app "$HOME"/goinfre/*/Ollama.app \
             "$HOME"/Downloads/Ollama.app "$HOME"/Desktop/Ollama.app; do
    [[ -d "$app" ]] || continue
    for sub in Contents/MacOS/ollama Contents/Resources/ollama; do
      if [[ -x "$app/$sub" ]]; then OLLAMA="$app/$sub"; add_try "найдено рядом: $app"; return 0; fi
    done
  done

  # 6. Spotlight — если индекс на этой машине вообще работает.
  cand="$(mdfind -name 'Ollama.app' 2>/dev/null | head -1)"
  if [[ -n "$cand" ]]; then
    add_try "Spotlight нашёл: $cand"
    for sub in Contents/MacOS/ollama Contents/Resources/ollama; do
      if [[ -x "$cand/$sub" ]]; then OLLAMA="$cand/$sub"; return 0; fi
    done
  else
    add_try "Spotlight: Ollama.app не найден"
  fi
  return 1
}

# Программу ищем всегда: при живом сервере она не обязательна, но с ней
# скачивание модели идёт с индикатором прогресса.
find_ollama >/dev/null 2>&1 || true

if server_up; then
  ok "Отвечает на $BASE_URL"
  [[ -n "$OLLAMA" ]] && say "     программа: $OLLAMA"
else
  say "На $BASE_URL никто не отвечает."
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
    say "Запустите сервер вручную — откройте Терминал и оставьте в нём:"
    say
    say "    ollama serve"
    say
    say "Затем, не закрывая то окно, запустите этот файл ещё раз."
    say
    say "Без Qwen кабинеты работают: режим «RAG по базе знаний» отвечает"
    say "по документам и модели не требует."
    finish 1
  fi
fi

# --- 2. Место под модель ----------------------------------------------------
head_ "2. Место под модель"

# Модель весит около гигабайта; с распаковкой и временными файлами нужно
# примерно вдвое больше. На учебных Mac домашняя квота обычно меньше —
# именно на этом Ollama и ломается: место кончается прямо во время
# скачивания, и дальше странно ведёт себя всё, включая саму Ollama.
NEED_KB=$((2 * 1024 * 1024))

free_kb() { df -Pk "$1" 2>/dev/null | tail -1 | awk '{print $4}'; }
human()   { df -Ph "$1" 2>/dev/null | tail -1 | awk '{print $4}'; }

# Где сервер держит модели сейчас: своей переменной у нас нет, поэтому
# исходим из того же правила, что и сам Ollama.
CUR_DIR="${OLLAMA_MODELS:-$HOME/.ollama/models}"
mkdir -p "$CUR_DIR" 2>/dev/null
CUR_FREE="$(free_kb "$CUR_DIR")"
say "Сейчас модели идут в: $CUR_DIR"
say "     свободно: $(human "$CUR_DIR") (нужно около 2 ГБ)"

USED="$(du -sh "$HOME/.ollama" 2>/dev/null | cut -f1)"
[[ -n "$USED" ]] && say "     уже занято папкой ~/.ollama: $USED"

# Запасная площадка: локальный диск учебной машины.
ALT_DIR=""
if [[ -d "$HOME/goinfre" ]]; then
  ALT_DIR="$HOME/goinfre/ollama-models"
fi

RELOCATE=0
if [[ -n "${CUR_FREE:-}" && "$CUR_FREE" -lt "$NEED_KB" ]]; then
  bad "Места не хватает: модель сюда не влезет."
  if [[ -n "$ALT_DIR" ]]; then
    mkdir -p "$ALT_DIR" 2>/dev/null
    ALT_FREE="$(free_kb "$ALT_DIR")"
    if [[ -n "${ALT_FREE:-}" && "$ALT_FREE" -ge "$NEED_KB" ]]; then
      say "     переношу модели на локальный диск: $ALT_DIR (свободно $(human "$ALT_DIR"))"
      RELOCATE=1
    else
      say "     на $ALT_DIR тоже мало: $(human "$ALT_DIR")"
    fi
  fi
  if [[ $RELOCATE -eq 0 ]]; then
    say
    say "Освободите около 2 ГБ и запустите этот файл заново."
    say "Место занимают в том числе прошлые незавершённые загрузки:"
    say "  du -sh ~/.ollama"
    finish 1
  fi
fi

if [[ $RELOCATE -eq 1 ]]; then
  # Переменная действует на сервер, а не на клиента, поэтому сервер
  # приходится перезапустить — иначе он продолжит писать в старую папку.
  say
  say "Перезапускаю сервер Ollama с новой папкой моделей…"
  if [[ -z "$OLLAMA" ]]; then
    bad "Программа Ollama не найдена — перезапустить сервер нечем."
    say "Сделайте это сами:"
    say "  pkill -f 'ollama serve'"
    say "  OLLAMA_MODELS=\"$ALT_DIR\" ollama serve"
    finish 1
  fi
  pkill -f 'ollama serve' >/dev/null 2>&1
  osascript -e 'quit app "Ollama"' >/dev/null 2>&1
  for _ in $(seq 1 10); do server_up || break; sleep 1; done
  export OLLAMA_MODELS="$ALT_DIR"
  LOG="${TMPDIR:-/tmp}/iins-ollama.log"
  nohup "$OLLAMA" serve > "$LOG" 2>&1 &
  for _ in $(seq 1 30); do sleep 1; server_up && break; done
  if server_up; then
    ok "Сервер перезапущен, модели идут в $ALT_DIR"
    say
    say "     Запомните эту команду: если запускать Ollama обычным способом,"
    say "     она вернётся к домашней папке, где места нет."
    say "     OLLAMA_MODELS=\"$ALT_DIR\" \"$OLLAMA\" serve"
    say
    say "     Впрочем, ./I-ins.command проверяет это при каждом запуске"
    say "     и при необходимости перезапускает сервер сам."
  else
    bad "Сервер не поднялся. Журнал: $LOG"
    finish 1
  fi
fi

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
    curl -fsS --no-buffer -m 7200 -X POST "$BASE_URL/api/pull" \
         -H 'Content-Type: application/json' \
         -d "{\"model\":\"$WANT_MODEL\",\"stream\":true}" \
      | awk '
          match($0, /"status"[ ]*:[ ]*"[^"]*"/) {
            s = substr($0, RSTART, RLENGTH); sub(/.*"status"[ ]*:[ ]*"/, "", s); sub(/"$/, "", s)
          }
          match($0, /"completed"[ ]*:[ ]*[0-9]+/) {
            c = substr($0, RSTART, RLENGTH); sub(/.*:[ ]*/, "", c) + 0
          }
          match($0, /"total"[ ]*:[ ]*[0-9]+/) {
            tt = substr($0, RSTART, RLENGTH); sub(/.*:[ ]*/, "", tt) + 0
          }
          {
            pct = (tt + 0 > 0) ? int((c + 0) * 100 / (tt + 0)) : -1
            if (pct >= 0 && pct >= shown + 5) { printf("  %s: %d%%\n", s, pct); shown = pct; fflush() }
            else if (s != last && pct < 0) { printf("  %s\n", s); fflush(); last = s }
          }
          END { printf("  готово\n") }'
    pulled=${PIPESTATUS[0]}
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
  if [[ $AUTO -eq 1 ]]; then
    say "     режимы «Авто» и «Qwen RAG» в кабинетах будут доступны"
    finish 0
  fi
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
