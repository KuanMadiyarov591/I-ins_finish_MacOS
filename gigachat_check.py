#!/usr/bin/env python3
"""Проверка связи с GigaChat: где именно рвётся цепочка.

Запускается отдельно от кабинетов и ничего в системе не меняет.

    python3 gigachat_check.py
    python3 gigachat_check.py --key sk-… --url https://…/v1 --model …

Пробует четыре способа обращения и по каждому печатает результат:

    1. urllib, набор корневых сертификатов по умолчанию   — так работает самопроверка;
    2. urllib с набором из certifi                        — обход проблемы python.org;
    3. httpx с набором по умолчанию                       — так работают кабинеты;
    4. httpx с набором из certifi.

Ошибка «certificate verify failed: unable to get local issuer certificate»
означает, что Python не видит корневых сертификатов. У сборок с python.org
это штатное состояние сразу после установки: они не пользуются связкой ключей
macOS, а свой набор ставят отдельной командой.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://gigachat-students.nsk.21-school.ru/v1"
DEFAULT_MODEL = "Gigashlep/GigaChat-2-Max"
QUESTION = "Скажи одним словом: работает"


def find_key() -> str:
    for var in ("GIGACHAT_API_KEY", "I_INS_GIGACHAT_KEY", "IINS_GIGACHAT_KEY"):
        value = (os.environ.get(var) or "").strip()
        if value:
            return value
    here = Path(__file__).resolve().parent
    candidates = [here / "gigachat.key", here.parent / "gigachat.key",
                  Path.home() / ".i-ins" / "gigachat.key"]
    data_root = os.environ.get("IINS_DATA_ROOT")
    if data_root:
        candidates.insert(0, Path(data_root).expanduser() / "gigachat.key")
    goinfre = Path.home() / "goinfre" / "I-ins" / "gigachat.key"
    candidates.append(goinfre)
    candidates.append(Path.home() / "Library" / "Application Support" / "I-ins" / "gigachat.key")
    for path in candidates:
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    print(f"Ключ взят из файла: {path}")
                    return value
        except OSError:
            continue
    return ""


def body(model: str) -> bytes:
    return json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай одним словом."},
            {"role": "user", "content": QUESTION},
        ],
        "max_tokens": 32,
        "temperature": 0.0,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")


def answer_of(raw: str) -> str:
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    first = choices[0] or {}
    content = (first.get("message") or {}).get("content") or first.get("text") or ""
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content).strip()


def try_urllib(url: str, key: str, model: str, context: ssl.SSLContext | None, label: str) -> bool:
    request = urllib.request.Request(
        f"{url}/chat/completions", data=body(model), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90.0, context=context) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        print(f"  [——] {label}: HTTP {exc.code} — {raw[:220]}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [——] {label}: {type(exc).__name__}: {exc}")
        return False
    text = answer_of(raw)
    if not text:
        print(f"  [——] {label}: HTTP {status}, но ответ пуст — {raw[:220]}")
        return False
    print(f"  [ок] {label}: HTTP {status}, ответ модели: {text[:120]}")
    return True


def try_httpx(url: str, key: str, model: str, verify, label: str) -> bool:  # noqa: ANN001
    try:
        import httpx
    except ImportError:
        print(f"  [ ] {label}: httpx не установлен — пропущено")
        return False
    try:
        with httpx.Client(timeout=90.0, trust_env=True, verify=verify) as client:
            r = client.post(
                f"{url}/chat/completions", content=body(model),
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json; charset=utf-8"},
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  [——] {label}: {type(exc).__name__}: {exc}")
        return False
    if r.status_code >= 400:
        print(f"  [——] {label}: HTTP {r.status_code} — {r.text[:220]}")
        return False
    text = answer_of(r.text)
    if not text:
        print(f"  [——] {label}: HTTP {r.status_code}, но ответ пуст — {r.text[:220]}")
        return False
    print(f"  [ок] {label}: HTTP {r.status_code}, ответ модели: {text[:120]}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка связи с GigaChat")
    parser.add_argument("--key", default="")
    parser.add_argument("--url", default=os.environ.get("GIGACHAT_BASE_URL") or DEFAULT_URL)
    parser.add_argument("--model", default=os.environ.get("GIGACHAT_MODEL") or DEFAULT_MODEL)
    args = parser.parse_args()

    url = args.url.rstrip("/")
    key = args.key.strip() or find_key()

    print("=" * 62)
    print(" Проверка GigaChat")
    print("=" * 62)
    print(f"Python:   {platform.python_version()} ({sys.executable})")
    print(f"Система:  {platform.system()} {platform.release()} / {platform.machine()}")
    print(f"OpenSSL:  {ssl.OPENSSL_VERSION}")
    paths = ssl.get_default_verify_paths()
    print(f"Корневые сертификаты по умолчанию: cafile={paths.cafile} capath={paths.capath}")
    try:
        import certifi
        certifi_path = certifi.where()
        print(f"certifi:  {certifi_path}")
    except ImportError:
        certifi_path = ""
        print("certifi:  не установлен")
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "HTTPS_PROXY", "https_proxy"):
        value = os.environ.get(name)
        if value:
            print(f"{name}: {value[:70]}")
    print(f"Адрес:    {url}")
    print(f"Модель:   {args.model}")
    print(f"Ключ:     {'задан, ' + str(len(key)) + ' знаков, ...' + key[-4:] if key else 'НЕ ЗАДАН'}")
    print()

    if not key:
        print("[ошибка] Ключ не найден. Передайте его: --key sk-…")
        return 2

    print("Запросы к модели:")
    results = {
        "urllib по умолчанию": try_urllib(url, key, args.model, None, "urllib, набор по умолчанию"),
    }
    if certifi_path:
        ctx = ssl.create_default_context(cafile=certifi_path)
        results["urllib + certifi"] = try_urllib(url, key, args.model, ctx, "urllib, набор certifi")
    results["httpx по умолчанию"] = try_httpx(url, key, args.model, True, "httpx, набор по умолчанию")
    if certifi_path:
        results["httpx + certifi"] = try_httpx(url, key, args.model, certifi_path, "httpx, набор certifi")

    print()
    ok = [name for name, good in results.items() if good]
    if not ok:
        print("Ни один способ не сработал.")
        print()
        if not paths.cafile and not certifi_path:
            print("Похоже, у этого Python вообще нет набора корневых сертификатов.")
        print("Если ошибка про certificate verify failed — Python с python.org не")
        print("пользуется связкой ключей macOS. Выполните один раз:")
        print('  /Applications/Python\\ 3.12/Install\\ Certificates.command')
        print("(вместо 3.12 подставьте свою версию), затем запустите проверку снова.")
        return 1

    print("Сработало:", ", ".join(ok))
    if certifi_path and not results.get("urllib по умолчанию") and results.get("urllib + certifi"):
        print()
        print("Диагноз: набор корневых сертификатов по умолчанию пуст или неполон,")
        print("а набор certifi работает. Кабинетам нужно указать его переменной")
        print(f"  export SSL_CERT_FILE={certifi_path}")
        print("Именно это и делает обновлённый I-ins.command.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
