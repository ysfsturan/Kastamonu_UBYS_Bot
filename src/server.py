"""Render / bulut sunucuları için 7/24 birleşik çalışma modu (--serve)."""

from __future__ import annotations

import copy
import json
import logging
import os
import signal
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from .bot_commands import process_telegram_commands
from .config import Config
from .differ import STATE_SCHEMA_VERSION, create_state_store

logger = logging.getLogger(__name__)

_CURSOR_KEYS = ("telegram_last_update_id", "telegram_commands_version")


def _now_tr() -> datetime:
    from .main import now_tr

    return now_tr()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_next_weekday_morning(
    now_dt: datetime,
    notify_hour: int,
    second_offset: int = 5,
) -> datetime:
    """Hafta içi (Pazartesi-Cuma) bir sonraki sabah bildirim zamanını döndürür."""
    candidate = now_dt.replace(
        hour=notify_hour,
        minute=0,
        second=second_offset,
        microsecond=0,
    )
    if candidate <= now_dt:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def compute_next_check_delay(
    now_dt: datetime,
    interval_minutes: int,
    morning_hour: Optional[int],
) -> tuple[float, datetime, str]:
    """Periyodik aralık ile hafta içi sabah hedefinden daha erken olanı seçer."""
    interval_target = now_dt + timedelta(minutes=max(1, int(interval_minutes)))
    target = interval_target
    reason = "interval"
    if morning_hour is not None:
        morning_target = compute_next_weekday_morning(now_dt, morning_hour)
        if morning_target <= interval_target:
            target = morning_target
            reason = "morning"
    delay_seconds = max(1.0, (target - now_dt).total_seconds())
    return delay_seconds, target, reason


class HealthState:
    """Render sağlık kontrolü (/health) için iş parçacığı güvenli durum tutucu."""

    def __init__(self, started_at: Optional[datetime] = None) -> None:
        self._lock = threading.Lock()
        self.started_at = started_at or _now_tr()
        self.last_check_at: Optional[datetime] = None
        self.last_check_ok: Optional[bool] = None
        self.next_check_at: Optional[datetime] = None
        self.next_check_reason: Optional[str] = None
        self.commands_handled: int = 0

    def record_check(self, checked_at: datetime, ok: bool) -> None:
        with self._lock:
            self.last_check_at = checked_at
            self.last_check_ok = ok

    def set_next_check(self, next_at: datetime, reason: str) -> None:
        with self._lock:
            self.next_check_at = next_at
            self.next_check_reason = reason

    def add_commands(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self.commands_handled += count

    def snapshot(self, current_dt: Optional[datetime] = None) -> dict[str, Any]:
        ref = current_dt or _now_tr()
        with self._lock:
            return {
                "status": "ok",
                "mode": "serve",
                "uptime_seconds": max(0, int((ref - self.started_at).total_seconds())),
                "started_at_tr": self.started_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "last_check_tr": (
                    self.last_check_at.strftime("%Y-%m-%d %H:%M:%S %Z")
                    if self.last_check_at
                    else None
                ),
                "last_check_ok": self.last_check_ok,
                "next_check_tr": (
                    self.next_check_at.strftime("%Y-%m-%d %H:%M:%S %Z")
                    if self.next_check_at
                    else None
                ),
                "next_check_reason": self.next_check_reason,
                "commands_handled": self.commands_handled,
            }


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def create_health_server(
    port: int,
    health_state: HealthState,
    host: str = "0.0.0.0",
) -> ThreadingHTTPServer:
    """Render Web Service ve keep-alive pinger'ları için hafif HTTP sunucusu oluşturur."""

    class HealthHandler(BaseHTTPRequestHandler):
        def _send_json(self, status_code: int, payload: dict[str, Any], send_body: bool) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if send_body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/health"}:
                self._send_json(200, health_state.snapshot(), send_body=True)
            else:
                self._send_json(404, {"status": "not_found"}, send_body=True)

        def do_HEAD(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/health"}:
                self._send_json(200, health_state.snapshot(), send_body=False)
            else:
                self._send_json(404, {"status": "not_found"}, send_body=False)

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("Health HTTP: " + format, *args)

    return _ReusableThreadingHTTPServer((host, port), HealthHandler)


def _resolve_port(port: Optional[int]) -> int:
    if port is not None:
        return port
    raw = os.getenv("PORT", "").strip()
    if not raw:
        return 10000
    try:
        return int(raw)
    except ValueError:
        logger.warning("Geçersiz PORT değeri (%r); varsayılan 10000 kullanılacak.", raw)
        return 10000


def _resolve_morning_hour(config: Config) -> Optional[int]:
    hours: list[int] = []
    if config.enable_dining or config.enable_weather:
        hours.append(config.dining_notify_hour)
    if config.enable_calendar:
        hours.append(config.calendar_notify_hour)
    if config.enable_schedule:
        hours.append(config.schedule_notify_hour)
    return min(hours) if hours else None


def _command_listener_loop(
    config: Config,
    state_store: Any,
    state_lock: threading.Lock,
    command_cursor: dict[str, Any],
    shared_swiss: dict[str, Any],
    health_state: HealthState,
    stop_event: threading.Event,
) -> None:
    logger.info("Telegram anlık komut dinleyici iş parçacığı başlatıldı.")
    while not stop_event.is_set():
        try:
            with state_lock:
                cmd_swiss = copy.deepcopy(shared_swiss)
                for key in _CURSOR_KEYS:
                    if key in command_cursor:
                        cmd_swiss[key] = command_cursor[key]

            ctx: dict[str, Any] = {
                "today": _now_tr().date(),
                "swiss_state": cmd_swiss,
            }
            handled, dirty = process_telegram_commands(
                config,
                cmd_swiss,
                ctx,
                poll_timeout=20,
            )
            if handled > 0:
                health_state.add_commands(handled)

            if dirty:
                with state_lock:
                    for key in _CURSOR_KEYS:
                        if key in cmd_swiss:
                            command_cursor[key] = cmd_swiss[key]
                            shared_swiss[key] = cmd_swiss[key]
                    try:
                        loaded = state_store.load()
                        working: dict[str, Any] = (
                            copy.deepcopy(loaded)
                            if isinstance(loaded, dict)
                            else {
                                "schema_version": STATE_SCHEMA_VERSION,
                                "baseline_initialized": False,
                                "courses": {},
                            }
                        )
                        swiss_block = dict(working.get("swiss_tool") or {})
                        for key in _CURSOR_KEYS:
                            if key in command_cursor:
                                swiss_block[key] = command_cursor[key]
                        working["swiss_tool"] = swiss_block
                        working["updated_at"] = _utc_now_iso()
                        state_store.save(working)
                    except Exception as save_exc:
                        logger.warning("Komut imleci kaydedilemedi: %s", save_exc)
        except Exception as exc:
            err_lower = str(exc).lower()
            if "409" in err_lower or "conflict" in err_lower:
                logger.warning(
                    "Telegram getUpdates çakışması (HTTP 409 - muhtemelen yeni dağıtım geçişi); 5 sn bekleniyor..."
                )
            else:
                logger.warning("Telegram komut dinleyicide geçici hata: %s", exc)
            stop_event.wait(timeout=5.0)


def run_serve(
    config: Config,
    port: Optional[int] = None,
    dump_html: bool = False,
) -> int:
    """Render ve sürekli sunucu ortamları için birleşik zamanlayıcı + Telegram komut dinleyici + HTTP health sunucusu."""
    from .main import run_once

    resolved_port = _resolve_port(port)
    health_state = HealthState()
    httpd = create_health_server(resolved_port, health_state)
    http_thread = threading.Thread(
        target=httpd.serve_forever,
        name="ubys-health-http",
        daemon=True,
    )
    http_thread.start()
    logger.info("HTTP sağlık sunucusu 0.0.0.0:%d adresinde başlatıldı (/health).", httpd.server_port)

    stop_event = threading.Event()
    prev_handlers: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        def _handle_signal(signum: int, _frame: Any) -> None:
            logger.info("Durdurma sinyali alındı (%s); sunucu kapatılıyor...", signum)
            stop_event.set()

        for sig_name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, sig_name, None)
            if sig is not None:
                try:
                    prev_handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, _handle_signal)
                except (OSError, ValueError):
                    pass

    state_store = create_state_store(
        state_file=config.state_file,
        gist_id=config.gist_id,
        gist_token=config.gist_token,
        gist_filename=config.gist_filename,
    )
    state_lock = threading.Lock()
    command_cursor: dict[str, Any] = {}
    shared_swiss: dict[str, Any] = {}

    try:
        initial_state = state_store.load()
        if isinstance(initial_state, dict) and isinstance(initial_state.get("swiss_tool"), dict):
            shared_swiss = copy.deepcopy(initial_state["swiss_tool"])
            for key in _CURSOR_KEYS:
                if key in shared_swiss:
                    command_cursor[key] = shared_swiss[key]
    except Exception as exc:
        logger.warning("Başlangıç durumu okunamadı (ilk kontrolde yeniden denenecek): %s", exc)

    cmd_thread: Optional[threading.Thread] = None
    if config.enable_commands and config.telegram_bot_token and config.telegram_chat_ids:
        cmd_thread = threading.Thread(
            target=_command_listener_loop,
            args=(
                config,
                state_store,
                state_lock,
                command_cursor,
                shared_swiss,
                health_state,
                stop_event,
            ),
            name="ubys-telegram-commands",
            daemon=True,
        )
        cmd_thread.start()
    else:
        logger.info("Telegram komut dinleyicisi devre dışı veya kimlik bilgileri eksik.")

    morning_hour = _resolve_morning_hour(config)
    logger.info(
        "Render 7/24 modu aktif (periyot: %d dk | hafta içi sabah hedefi: %s).",
        config.check_interval_minutes,
        f"{morning_hour:02d}:00 TR" if morning_hour is not None else "kapalı",
    )

    try:
        while not stop_event.is_set():
            swiss_out: dict[str, Any] = {}
            try:
                rc = run_once(
                    config,
                    dump_html=dump_html,
                    run_commands=False,
                    state_lock=state_lock,
                    command_cursor=command_cursor,
                    swiss_state_out=swiss_out,
                )
            except Exception as exc:
                logger.exception("Zamanlanmış kontrol sırasında beklenmeyen hata: %s", exc)
                rc = 1

            with state_lock:
                if swiss_out:
                    shared_swiss.clear()
                    shared_swiss.update(swiss_out)
                    for key in _CURSOR_KEYS:
                        if key in command_cursor:
                            shared_swiss[key] = command_cursor[key]

            now_dt = _now_tr()
            health_state.record_check(now_dt, rc == 0)
            delay_sec, next_dt, reason = compute_next_check_delay(
                now_dt,
                config.check_interval_minutes,
                morning_hour,
            )
            health_state.set_next_check(next_dt, reason)
            logger.info(
                "Sonraki kontrol (%s): %s TR (%.0f sn sonra).",
                "hafta içi sabah 08:00 hedefi" if reason == "morning" else "periyodik kontrol",
                next_dt.strftime("%Y-%m-%d %H:%M:%S"),
                delay_sec,
            )
            stop_event.wait(timeout=delay_sec)
    except KeyboardInterrupt:
        logger.info("Kullanıcı tarafından durduruldu.")
    finally:
        stop_event.set()
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass
        if cmd_thread is not None and cmd_thread.is_alive():
            cmd_thread.join(timeout=5.0)
        for sig, prev in prev_handlers.items():
            try:
                signal.signal(sig, prev)
            except (OSError, ValueError):
                pass

    return 0
