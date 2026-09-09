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

# Тело ответа Ollama при ошибке: там причина, а не в номере статуса.
err_text() {
  sed -n 's/.*"error"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' <<< "$1" | head -1
}

# Модель может числиться в списке, но не работать: если загрузка оборвалась,
# манифест уже записан, а файлы весов — нет. Поэтому проверяем не наличие,
# а работоспособность: просим сказать одно слово.
model_answers() {
  local out code
  out="$(curl -sS -m 180 -w $'\n%{http_code}' -X POST "$BASE_URL/api/chat" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"привет\"}],\"stream\":false,\"options\":{\"num_predict\":8}}" 2>&1)"
  code="$(tail -1 <<< "$out")"
  LAST_ERR="$(err_text "$out")"
  [[ "$code" == "200" ]]
}

pull_model() {
  curl -fsS --no-buffer -m 7200 -X POST "$BASE_URL/api/pull" \
       -H 'Content-Type: application/json' \
       -d "{\"model\":\"$1\",\"stream\":true}" \
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
        }'
  return ${PIPESTATUS[0]}
}

drop_model() {
  curl -fsS -m 60 -X DELETE "$BASE_URL/api/delete" \
       -H 'Content-Type: application/json' -d "{\"model\":\"$1\"}" >/dev/null 2>&1
}

# --- 1. Отвечает ли сервер --------------------------------------------------
head_ "1. Сервер Ollama"

OLLAMA=""
APP_BUNDLE=""
add_try() { TRIED="$TRIED  $1"$'\n'; }

# Внутри Ollama.app два разных исполняемых файла: в Contents/MacOS лежит
# само приложение с окном, а программа командной строки — в Contents/Resources.
# Если запустить первое с аргументом pull, оно просто откроет окно и будет
# висеть: именно на этом всё и останавливалось.
to_cli() {
  local p="$1" bundle
  case "$p" in
    */Contents/MacOS/*)
      bundle="${p%/Contents/MacOS/*}"
      APP_BUNDLE="${APP_BUNDLE:-$bundle}"
      if [[ -x "$bundle/Contents/Resources/ollama" ]]; then
        printf '%s' "$bundle/Contents/Resources/ollama"
      fi
      return 0 ;;
  esac
  printf '%s' "$p"
}

find_ollama() {
  local cand sh seen_sh sub app rc

  # 1. PATH текущей оболочки.
  cand="$(command -v ollama 2>/dev/null || true)"
  add_try "PATH этой оболочки: ${cand:-не найдено}"
  cand="$(to_cli "$cand")"
  if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

  # 2. Псевдоним из ~/.zshrc. Очень частый случай: программа лежит там, где
  #    есть место, а в профиле на неё сделан alias. Псевдонимы живут только
  #    в интерактивной оболочке, поэтому обычный `command -v` их не видит.
  if [[ -x /bin/zsh ]]; then
    cand="$(/bin/zsh -ic 'whence -p ollama' 2>/dev/null | tail -1)"
    add_try "интерактивный zsh, обычный путь: ${cand:-не найдено}"
    cand="$(to_cli "$cand")"
  if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

    cand="$(/bin/zsh -ic 'alias ollama' 2>/dev/null | tail -1 \
            | sed -e 's/^ollama=//' -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//')"
    add_try "псевдоним ollama: ${cand:-не найдено}"
    cand="$(to_cli "$cand")"
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
  cand="$(to_cli "$cand")"
  if [[ -n "$cand" && -x "$cand" ]]; then OLLAMA="$cand"; return 0; fi

  # 4. Известные места. goinfre идёт первым: на учебных Mac программу ставят
  #    именно туда, потому что в домашней папке нет места.
  for cand in \
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
    /Applications/Ollama.app/Contents/Resources/ollama \
    "$HOME/Applications/Ollama.app/Contents/Resources/ollama"
  do
    if [[ -x "$cand" ]]; then OLLAMA="$cand"; add_try "по известному пути: $cand"; return 0; fi
  done
  add_try "по известным путям: не найдено"

  # 5. Обход папок, где вообще может лежать Ollama.app.
  for app in "$HOME"/goinfre/Ollama.app "$HOME"/goinfre/*/Ollama.app \
             "$HOME"/Downloads/Ollama.app "$HOME"/Desktop/Ollama.app; do
    [[ -d "$app" ]] || continue
    if [[ -x "$app/Contents/Resources/ollama" ]]; then
      OLLAMA="$app/Contents/Resources/ollama"; add_try "найдено рядом: $app"; return 0
    fi
    APP_BUNDLE="${APP_BUNDLE:-$app}"
  done

  # 6. Spotlight — если индекс на этой машине вообще работает.
  cand="$(mdfind -name 'Ollama.app' 2>/dev/null | head -1)"
  if [[ -n "$cand" ]]; then
    add_try "Spotlight нашёл: $cand"
    APP_BUNDLE="${APP_BUNDLE:-$cand}"
    if [[ -x "$cand/Contents/Resources/ollama" ]]; then
      OLLAMA="$cand/Contents/Resources/ollama"; return 0
    fi
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
  else
    # Программы командной строки нет, но само приложение может быть — оно
    # поднимает сервер само, достаточно его открыть.
    seen_app=""
    for app in "$APP_BUNDLE" "$HOME/goinfre/Ollama.app" /Applications/Ollama.app \
               "$HOME/Applications/Ollama.app"; do
      [[ -n "$app" && -d "$app" ]] || continue
      case "$seen_app" in *"|$app|"*) continue ;; esac
      seen_app="$seen_app|$app|"
      ok "Открываю приложение: $app"
      open -a "$app" >/dev/null 2>&1
      for _ in $(seq 1 30); do sleep 1; server_up && break; done
      server_up && break
    done
  fi

  if server_up; then
    ok "Сервер поднялся"
  else
    bad "Сервер не отвечает."
    say
    say "Где я искал программу:"
    printf '%s' "$TRIED"
    say
    say "Запустите Ollama сами — проще всего открыть само приложение"
    say "(двойным щелчком по Ollama.app). Или в Терминале, оставив окно:"
    say
    say "    ollama serve"
    say
    say "Затем запустите этот файл ещё раз."
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
# именно на этом Ollama и ломается: место кончается прямо во время загрузки.
NEED_KB=$((2 * 1024 * 1024))

free_kb() { df -Pk "$1" 2>/dev/null | tail -1 | awk '{print $4}'; }
human()   { df -Ph "$1" 2>/dev/null | tail -1 | awk '{print $4}'; }

STORE="$HOME/.ollama/models"
ALT_DIR="$HOME/goinfre/ollama-models"

# Если папка моделей уже ссылка на просторный диск — чинить нечего.
if [[ -L "$STORE" ]]; then
  TARGET="$(readlink "$STORE")"
  mkdir -p "$TARGET" 2>/dev/null
  ok "Модели уже вынесены на другой диск: $TARGET"
  say "     свободно: $(human "$TARGET")"
else
  mkdir -p "$STORE" 2>/dev/null
  CUR_FREE="$(free_kb "$STORE")"
  say "Модели лежат в: $STORE"
  say "     свободно: $(human "$STORE") (нужно около 2 ГБ)"

  if [[ -n "${CUR_FREE:-}" && "$CUR_FREE" -lt "$NEED_KB" ]]; then
    bad "Столько сюда не влезет."
    if [[ -d "$HOME/goinfre" ]]; then
      mkdir -p "$ALT_DIR" 2>/dev/null
      ALT_FREE="$(free_kb "$ALT_DIR")"
      if [[ -n "${ALT_FREE:-}" && "$ALT_FREE" -ge "$NEED_KB" ]]; then
        say "     выношу хранилище на локальный диск: $ALT_DIR (свободно $(human "$ALT_DIR"))"
        # Ссылка вместо переменной окружения: работает при любом способе
        # запуска Ollama — и из окна, и из командной строки, — и переживает
        # перезагрузку. Перезапускать сервер не нужно.
        if [[ -d "$STORE" ]]; then
          ( cd "$STORE" && tar cf - . 2>/dev/null ) | ( cd "$ALT_DIR" && tar xf - 2>/dev/null )
          rm -rf "$STORE" 2>/dev/null
        fi
        if ln -s "$ALT_DIR" "$STORE" 2>/dev/null; then
          ok "Готово: $STORE теперь ведёт в $ALT_DIR"
        else
          bad "Не удалось создать ссылку $STORE"
          say "Сделайте вручную:"
          say "  mkdir -p \"$ALT_DIR\" && rm -rf \"$STORE\" && ln -s \"$ALT_DIR\" \"$STORE\""
          finish 1
        fi
      else
        bad "На $ALT_DIR тоже мало: $(human "$ALT_DIR")"
        say "Освободите около 2 ГБ и запустите этот файл заново."
        finish 1
      fi
    else
      say
      say "Освободите около 2 ГБ и запустите этот файл заново."
      say "Посмотреть, что занимает место:  du -sh ~/.ollama ~/Library/Caches"
      finish 1
    fi
  fi
fi

# --- 3. Модель ---------------------------------------------------------------
head_ "3. Модель"

LAST_ERR=""
CHOSEN="$(qwen_present || true)"

if [[ -z "$CHOSEN" ]]; then
  ALL="$(model_names | paste -sd, - | sed 's/,/, /g')"
  [[ -z "$ALL" ]] && ALL="их нет"
  bad "Моделей Qwen нет (сейчас скачано: $ALL)"
  say
  say "Скачиваю $WANT_MODEL — это около 1 ГБ, займёт несколько минут."
  say
  if pull_model "$WANT_MODEL"; then
    CHOSEN="$(qwen_present || true)"
  fi
  if [[ -z "$CHOSEN" ]]; then
    bad "Скачать не удалось — проверьте связь и свободное место."
    finish 1
  fi
  ok "Скачана: $CHOSEN"
else
  ok "Модель числится в списке: $CHOSEN"
fi

# Наличие в списке ничего не гарантирует: при оборванной загрузке манифест
# записан, а файлы весов — нет. Такая модель видна, но на первом же вопросе
# отвечает пятисотой ошибкой. Поэтому спрашиваем её по-настоящему.
say "Проверяю, отвечает ли она (первый запуск может занять полминуты)…"
if model_answers "$CHOSEN"; then
  ok "Отвечает"
else
  bad "Не отвечает: ${LAST_ERR:-сервер вернул ошибку}"
  case "$(printf '%s' "$LAST_ERR" | tr 'A-Z' 'a-z')" in
    *memory*|*insufficient*)
      say
      say "Не хватает оперативной памяти. Закройте тяжёлые программы или"
      say "возьмите модель поменьше:"
      say "  OLLAMA_MODEL=qwen2.5:0.5b ./QWEN_SETUP.command"
      finish 1 ;;
  esac
  say
  say "Похоже, файлы модели неполные — загрузка когда-то оборвалась."
  say "Удаляю и качаю заново."
  say
  drop_model "$CHOSEN"
  if ! pull_model "$WANT_MODEL"; then
    bad "Скачать заново не удалось."
    finish 1
  fi
  CHOSEN="$(qwen_present || true)"
  if [[ -z "$CHOSEN" ]]; then
    bad "После повторной загрузки модель не появилась в списке."
    finish 1
  fi
  say
  say "Проверяю ещё раз…"
  if model_answers "$CHOSEN"; then
    ok "Теперь отвечает: $CHOSEN"
  else
    bad "По-прежнему не отвечает: ${LAST_ERR:-сервер вернул ошибку}"
    say
    say "Это уже не про загрузку. Посмотрите, что скажет сама Ollama:"
    say "  curl -s $BASE_URL/api/chat -d '{\"model\":\"$CHOSEN\",\"messages\":[{\"role\":\"user\",\"content\":\"привет\"}],\"stream\":false}'"
    say
    say "Кабинеты продолжат работать в режиме «RAG по базе знаний»."
    finish 1
  fi
fi

[[ "$CHOSEN" != "$WANT_MODEL" ]] && say "     кабинеты возьмут её вместо $WANT_MODEL — это нормально"

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
