"""Kastamonu Üniversitesi (Kuzeykent Kampüsü) Open-Meteo & wttr.in yedekli hava durumu modülü."""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Optional

import httpx

from .models import WeatherForecast

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WTTR_BASE_URL = "https://wttr.in"

_WWO_TO_WMO: dict[int, int] = {
    113: 0,
    116: 2,
    119: 3,
    122: 3,
    143: 45,
    176: 80,
    179: 85,
    182: 66,
    185: 56,
    200: 95,
    227: 71,
    230: 75,
    248: 48,
    260: 48,
    263: 51,
    266: 51,
    281: 56,
    284: 57,
    293: 61,
    296: 61,
    299: 63,
    302: 63,
    305: 65,
    308: 65,
    311: 66,
    314: 67,
    317: 66,
    320: 71,
    323: 71,
    326: 71,
    329: 73,
    332: 73,
    335: 75,
    338: 75,
    350: 77,
    353: 80,
    356: 81,
    359: 82,
    362: 66,
    365: 67,
    368: 85,
    371: 86,
    374: 77,
    377: 77,
    386: 95,
    389: 95,
    392: 96,
    395: 99,
}

WMO_CODE_MAP: dict[int, tuple[str, str]] = {
    0: ("Açık / Güneşli", "☀️"),
    1: ("Az Bulutlu", "🌤️"),
    2: ("Parçalı Bulutlu", "⛅"),
    3: ("Çok Bulutlu", "☁️"),
    45: ("Sisli", "🌫️"),
    48: ("Kırağı / Yoğun Sis", "🌫️"),
    51: ("Hafif Çiseleme", "🌦️"),
    53: ("Çiseleme", "🌦️"),
    55: ("Yoğun Çiseleme", "🌧️"),
    56: ("Dondurucu Çiseleme", "🌧️"),
    57: ("Yoğun Dondurucu Çiseleme", "🌧️"),
    61: ("Hafif Yağmur", "🌦️"),
    63: ("Yağmurlu", "🌧️"),
    65: ("Kuvvetli Yağmur", "🌧️"),
    66: ("Dondurucu Yağmur", "🌧️"),
    67: ("Şiddetli Dondurucu Yağmur", "🌧️"),
    71: ("Hafif Kar Yağışlı", "🌨️"),
    73: ("Kar Yağışlı", "❄️"),
    75: ("Yoğun Kar Yağışlı", "❄️"),
    77: ("Kar Taneleri", "🌨️"),
    80: ("Hafif Sağanak", "🌦️"),
    81: ("Sağanak Yağış", "🌧️"),
    82: ("Şiddetli Sağanak", "⛈️"),
    85: ("Hafif Kar Sağanağı", "🌨️"),
    86: ("Yoğun Kar Sağanağı", "❄️"),
    95: ("Gökgürültülü Sağanak", "⛈️"),
    96: ("Dolu / Fırtına", "⛈️"),
    99: ("Şiddetli Dolu Fırtınası", "⛈️"),
}


class WeatherError(Exception):
    """Hava durumu verisi alınırken veya ayrıştırılırken oluşan hata."""


def describe_wmo_code(code: int) -> tuple[str, str]:
    """Open-Meteo WMO hava kodunu Türkçe açıklama ve emoji ikilisine çevirir."""
    if code in WMO_CODE_MAP:
        return WMO_CODE_MAP[code]
    if 1 <= code <= 3:
        return ("Parçalı Bulutlu", "⛅")
    if 40 <= code <= 49:
        return ("Sisli", "🌫️")
    if 50 <= code <= 69 or 80 <= code <= 82:
        return ("Yağmurlu", "🌧️")
    if 70 <= code <= 79 or code in {85, 86}:
        return ("Kar Yağışlı", "❄️")
    if code >= 95:
        return ("Fırtına", "⛈️")
    return ("Değişken", "🌡️")


def _opt_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _opt_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def build_weather_advice(
    temp_min: Optional[float],
    temp_max: Optional[float],
    precip_prob: Optional[int],
    wind_speed: Optional[float],
    weather_code: int,
) -> str:
    """Kampüs şartlarına göre pratik günlük kıyafet/hava tavsiyesi üretir."""
    tips: list[str] = []
    if weather_code in {71, 73, 75, 77, 85, 86}:
        tips.append("Kar yağışı bekleniyor; kalın mont ve kaymaz bot tercih et")
    elif weather_code in {95, 96, 99}:
        tips.append("Fırtına uyarısı; şemsiye ve su geçirmez dış giyim al")
    elif weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82} or (
        precip_prob is not None and precip_prob >= 50
    ):
        tips.append("Yağış ihtimali yüksek; yanına şemsiye al")

    if temp_min is not None and temp_min <= 0.0:
        tips.append("Sabah/akşam ayaz ve don riski var; sıkı giyin")
    elif temp_min is not None and temp_min <= 6.0:
        tips.append("Sabah saatleri serin; mont/hırka almayı unutma")
    elif temp_max is not None and temp_max >= 27.0:
        tips.append("Sıcak bir gün; su şişeni ve güneş gözlüğünü unutma")

    if wind_speed is not None and wind_speed >= 30.0:
        tips.append("Rüzgâr kuvvetli esebilir")

    if not tips:
        return "Kampüs için dengeli ve rahat bir hava bekleniyor"
    return ". ".join(tips) + "."


def parse_open_meteo_response(
    data: dict[str, Any],
    location_name: str = "Kastamonu (Kuzeykent)",
) -> WeatherForecast:
    """Open-Meteo JSON yanıtını WeatherForecast nesnesine dönüştürür."""
    if not isinstance(data, dict):
        raise WeatherError("Hava durumu yanıtı beklenen JSON formatında değil.")

    current = data.get("current") or {}
    daily = data.get("daily") or {}

    times = daily.get("time") or []
    daily_codes = daily.get("weather_code") or []
    daily_mins = daily.get("temperature_2m_min") or []
    daily_maxs = daily.get("temperature_2m_max") or []
    daily_precips = daily.get("precipitation_probability_max") or []

    forecast_date = date.today()
    if times and isinstance(times[0], str):
        try:
            forecast_date = date.fromisoformat(times[0][:10])
        except ValueError:
            pass

    curr_code = _opt_int(current.get("weather_code"))
    if curr_code is None and daily_codes:
        curr_code = _opt_int(daily_codes[0])
    weather_code = curr_code if curr_code is not None else 0

    cond_text, cond_icon = describe_wmo_code(weather_code)
    current_temp = _opt_float(current.get("temperature_2m"))
    apparent_temp = _opt_float(current.get("apparent_temperature"))
    wind_speed = _opt_float(current.get("wind_speed_10m"))

    temp_min = _opt_float(daily_mins[0]) if daily_mins else None
    temp_max = _opt_float(daily_maxs[0]) if daily_maxs else None
    precip_prob = _opt_int(daily_precips[0]) if daily_precips else None

    daily_summaries: list[str] = []
    for idx, t_str in enumerate(times[:3]):
        try:
            d_obj = date.fromisoformat(str(t_str)[:10])
            d_label = d_obj.strftime("%d.%m")
        except ValueError:
            d_label = str(t_str)
        d_code = _opt_int(daily_codes[idx]) if idx < len(daily_codes) else None
        d_txt, d_ico = describe_wmo_code(d_code if d_code is not None else 0)
        d_min = _opt_float(daily_mins[idx]) if idx < len(daily_mins) else None
        d_max = _opt_float(daily_maxs[idx]) if idx < len(daily_maxs) else None
        d_prec = _opt_int(daily_precips[idx]) if idx < len(daily_precips) else None

        temp_part = (
            f"{d_min:.0f}°/{d_max:.0f}°C"
            if (d_min is not None and d_max is not None)
            else "-"
        )
        prec_part = f" (Yağış %{d_prec})" if d_prec is not None else ""
        daily_summaries.append(f"{d_label}: {d_ico} {d_txt}, {temp_part}{prec_part}")

    tomorrow_summary = daily_summaries[1] if len(daily_summaries) >= 2 else None
    advice = build_weather_advice(
        temp_min=temp_min if temp_min is not None else current_temp,
        temp_max=temp_max if temp_max is not None else current_temp,
        precip_prob=precip_prob,
        wind_speed=wind_speed,
        weather_code=weather_code,
    )

    return WeatherForecast(
        location_name=location_name,
        forecast_date=forecast_date,
        current_temp=current_temp,
        apparent_temp=apparent_temp,
        temp_min=temp_min,
        temp_max=temp_max,
        precip_probability=precip_prob,
        wind_speed=wind_speed,
        weather_code=weather_code,
        condition_text=cond_text,
        condition_icon=cond_icon,
        advice=advice,
        tomorrow_summary=tomorrow_summary,
        daily_summaries=daily_summaries,
    )


def _build_ipv4_transport() -> Optional[httpx.HTTPTransport]:
    try:
        return httpx.HTTPTransport(local_address="0.0.0.0")
    except OSError:
        return None


def _wwo_to_wmo(wwo_code: Optional[int]) -> int:
    if wwo_code is None:
        return 0
    return _WWO_TO_WMO.get(wwo_code, 2)


def parse_wttr_response(
    data: dict[str, Any],
    location_name: str = "Kastamonu (Kuzeykent)",
) -> WeatherForecast:
    """wttr.in ?format=j1 JSON yanıtını WeatherForecast nesnesine dönüştürür."""
    if not isinstance(data, dict):
        raise WeatherError("wttr.in hava durumu yanıtı beklenen JSON formatında değil.")

    curr_list = data.get("current_condition") or []
    curr = curr_list[0] if curr_list and isinstance(curr_list[0], dict) else {}
    daily_list = data.get("weather") or []

    forecast_date = date.today()
    if daily_list and isinstance(daily_list[0], dict) and daily_list[0].get("date"):
        try:
            forecast_date = date.fromisoformat(str(daily_list[0]["date"])[:10])
        except ValueError:
            pass

    curr_wwo = _opt_int(curr.get("weatherCode"))
    weather_code = _wwo_to_wmo(curr_wwo)
    cond_text, cond_icon = describe_wmo_code(weather_code)
    current_temp = _opt_float(curr.get("temp_C"))
    apparent_temp = _opt_float(curr.get("FeelsLikeC"))
    wind_speed = _opt_float(curr.get("windspeedKmph"))

    daily_summaries: list[str] = []
    today_min: Optional[float] = None
    today_max: Optional[float] = None
    today_precip: Optional[int] = None

    for idx, day_obj in enumerate(daily_list[:3]):
        if not isinstance(day_obj, dict):
            continue
        raw_d = str(day_obj.get("date") or "")
        try:
            d_label = date.fromisoformat(raw_d[:10]).strftime("%d.%m")
        except ValueError:
            d_label = raw_d or "-"

        d_min = _opt_float(day_obj.get("mintempC"))
        d_max = _opt_float(day_obj.get("maxtempC"))
        hourly = day_obj.get("hourly") or []
        rain_chances = [
            ch for ch in (_opt_int(h.get("chanceofrain")) for h in hourly if isinstance(h, dict))
            if ch is not None
        ]
        d_prec = max(rain_chances) if rain_chances else None

        mid_slot = hourly[len(hourly) // 2] if hourly and isinstance(hourly[len(hourly) // 2], dict) else {}
        d_wmo = _wwo_to_wmo(_opt_int(mid_slot.get("weatherCode")) if mid_slot else curr_wwo)
        d_txt, d_ico = describe_wmo_code(d_wmo)

        if idx == 0:
            today_min = d_min
            today_max = d_max
            today_precip = d_prec

        temp_part = f"{d_min:.0f}°/{d_max:.0f}°C" if (d_min is not None and d_max is not None) else "-"
        prec_part = f" (Yağış %{d_prec})" if d_prec is not None else ""
        daily_summaries.append(f"{d_label}: {d_ico} {d_txt}, {temp_part}{prec_part}")

    tomorrow_summary = daily_summaries[1] if len(daily_summaries) >= 2 else None
    advice = build_weather_advice(
        temp_min=today_min if today_min is not None else current_temp,
        temp_max=today_max if today_max is not None else current_temp,
        precip_prob=today_precip,
        wind_speed=wind_speed,
        weather_code=weather_code,
    )

    return WeatherForecast(
        location_name=location_name,
        forecast_date=forecast_date,
        current_temp=current_temp,
        apparent_temp=apparent_temp,
        temp_min=today_min,
        temp_max=today_max,
        precip_probability=today_precip,
        wind_speed=wind_speed,
        weather_code=weather_code,
        condition_text=cond_text,
        condition_icon=cond_icon,
        advice=advice,
        tomorrow_summary=tomorrow_summary,
        daily_summaries=daily_summaries,
    )


def fetch_weather_forecast(
    lat: float = 41.4307,
    lon: float = 33.7764,
    location_name: str = "Kastamonu (Kuzeykent)",
    timeout: float = 15.0,
) -> WeatherForecast:
    """Open-Meteo (ve hata halinde wttr.in) üzerinden Kastamonu hava tahminini çeker."""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Europe/Istanbul",
        "forecast_days": 3,
    }
    client_kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(timeout, connect=min(10.0, timeout)),
        "follow_redirects": True,
    }
    transport = _build_ipv4_transport()
    if transport is not None:
        client_kwargs["transport"] = transport

    open_meteo_err: Optional[Exception] = None
    with httpx.Client(**client_kwargs) as client:
        for attempt in range(2):
            try:
                resp = client.get(OPEN_METEO_URL, params=params)
                if resp.status_code == 200:
                    return parse_open_meteo_response(resp.json(), location_name=location_name)
                open_meteo_err = WeatherError(f"Open-Meteo HTTP {resp.status_code}")
                if resp.status_code not in {429, 500, 502, 503, 504}:
                    break
            except (httpx.HTTPError, ValueError, WeatherError) as exc:
                open_meteo_err = exc
            if attempt == 0:
                time.sleep(1.0)

        logger.warning("Open-Meteo alınamadı (%s); wttr.in yedek kaynağı deneniyor...", open_meteo_err)
        try:
            wttr_url = f"{WTTR_BASE_URL}/{lat:.4f},{lon:.4f}"
            resp_wttr = client.get(wttr_url, params={"format": "j1"})
            if resp_wttr.status_code == 200:
                return parse_wttr_response(resp_wttr.json(), location_name=location_name)
            raise WeatherError(f"wttr.in HTTP {resp_wttr.status_code}")
        except WeatherError:
            raise
        except (httpx.HTTPError, ValueError) as wttr_exc:
            raise WeatherError(
                f"Hava durumu alınamadı (Open-Meteo: {open_meteo_err}; wttr.in: {wttr_exc})"
            ) from wttr_exc
