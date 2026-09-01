"""Совместимость счётчиков Prometheus с новыми версиями FastAPI.

Начиная с FastAPI 0.141 в app.routes попадают объекты включённых роутеров,
у которых нет атрибута path. prometheus-fastapi-instrumentator обращается к
нему без проверки, и каждый запрос падает с AttributeError — именно так
кабинеты клиента и администратора переставали отвечать, тогда как остальные
четыре, не подключающие счётчики, работали.

Шим заменяет разбор маршрута на устойчивый: объект без path обходится вглубь,
а при любой неожиданности имя маршрута просто не определяется — счётчик
теряет шаблон пути, приложение продолжает отвечать.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def apply_route_name_shim() -> bool:
    """Ставит устойчивый разбор маршрута. True — шим установлен."""
    try:
        from prometheus_fastapi_instrumentator import routing
        from starlette.routing import Match, Mount
    except Exception as exc:  # noqa: BLE001
        _log.debug("prometheus routing shim skipped: %s", exc)
        return False

    if getattr(routing, "_iins_route_shim", False):
        return True

    def _route_name(scope, routes, route_name=None):  # noqa: ANN001, ANN202
        for route in routes:
            try:
                match, child_scope = route.matches(scope)
            except Exception:  # noqa: BLE001, PERF203
                continue
            path = getattr(route, "path", None)
            inner = getattr(route, "routes", None)
            if match == Match.FULL:
                if path is None:
                    if inner:
                        return _route_name({**scope, **child_scope}, inner, route_name)
                    return route_name
                if isinstance(route, Mount) and inner:
                    tail = _route_name({**scope, **child_scope}, inner, path)
                    return None if tail is None else path + tail
                return path
            if match == Match.PARTIAL and route_name is None and path is not None:
                route_name = path
        return None

    routing._get_route_name = _route_name
    routing._iins_route_shim = True
    return True
