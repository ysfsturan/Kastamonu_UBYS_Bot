"""Kastamonu Üniversitesi (Kuzeykent Kampüsü) ücretsiz Open-Meteo hava durumu modülü."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import httpx

from .models import WeatherForecast

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

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


def fetch_weather_forecast(
    lat: float = 41.4307,
    lon: float = 33.7764,
    location_name: str = "Kastamonu (Kuzeykent)",
    timeout: float = 15.0,
) -> WeatherForecast:
    """Open-Meteo API üzerinden güncel ve 3 günlük Kastamonu hava tahminini çeker."""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Europe/Istanbul",
        "forecast_days": 3,
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(OPEN_METEO_URL, params=params)
            if resp.status_code >= 400:
                raise WeatherError(f"Hava durumu API hatası: HTTP {resp.status_code}")
            return parse_open_meteo_response(resp.json(), location_name=location_name)
    except WeatherError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherError(f"Hava durumu alınamadı: {exc}") from exc
