from __future__ import annotations

import logging
from datetime import datetime, timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.util import dt as dt_util

from .const import (
    API_URL,
    CONF_API_KEY,
    CONF_BATTERY_ENTITY,
    CONF_GRID_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

BUCKET_MINUTES = 15

type HaPiloteComConfigEntry = ConfigEntry


def _bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0)


def _aggregate_15min(states: list, period_start: datetime, period_end: datetime) -> list[dict]:
    samples = []
    for state in states:
        if state.state in ("unavailable", "unknown"):
            continue
        try:
            value = float(state.state)
        except ValueError:
            continue
        samples.append((state.last_updated, value))

    if not samples:
        return []

    samples.sort(key=lambda s: s[0])

    buckets = {}
    bucket_dt = _bucket_start(period_start)
    while bucket_dt < period_end:
        buckets[bucket_dt] = {"weighted_sum": 0.0, "total_seconds": 0.0}
        bucket_dt += timedelta(minutes=BUCKET_MINUTES)

    for bucket_dt in sorted(buckets.keys()):
        bucket_end = bucket_dt + timedelta(minutes=BUCKET_MINUTES)

        relevant = []
        last_before = None
        for ts, val in samples:
            if ts < bucket_dt:
                last_before = val
            elif ts < bucket_end:
                relevant.append((ts, val))

        if not relevant and last_before is None:
            del buckets[bucket_dt]
            continue

        current_val = last_before if last_before is not None else relevant[0][1]
        cursor = bucket_dt

        for ts, val in relevant:
            dt_seconds = (ts - cursor).total_seconds()
            if dt_seconds > 0:
                buckets[bucket_dt]["weighted_sum"] += current_val * dt_seconds
                buckets[bucket_dt]["total_seconds"] += dt_seconds
            current_val = val
            cursor = ts

        dt_seconds = (bucket_end - cursor).total_seconds()
        if dt_seconds > 0:
            buckets[bucket_dt]["weighted_sum"] += current_val * dt_seconds
            buckets[bucket_dt]["total_seconds"] += dt_seconds

    result = []
    for bucket_dt in sorted(buckets.keys()):
        b = buckets[bucket_dt]
        if b["total_seconds"] > 0:
            avg = round(b["weighted_sum"] / b["total_seconds"], 1)
            result.append({
                "timestamp": bucket_dt.isoformat(),
                "value": avg,
            })

    return result


def _split_signed(history: list[dict]) -> tuple[list[dict], list[dict]]:
    positive = []
    negative = []
    for point in history:
        ts = point["timestamp"]
        val = point["value"]
        if val >= 0:
            positive.append({"timestamp": ts, "value": val})
            negative.append({"timestamp": ts, "value": 0.0})
        else:
            positive.append({"timestamp": ts, "value": 0.0})
            negative.append({"timestamp": ts, "value": abs(val)})
    return positive, negative


async def _get_history(hass, start, now, entity_id):
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        start,
        now,
        entity_id,
    )
    return _aggregate_15min(states.get(entity_id, []), start, now)


async def async_setup_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    production_entity = entry.data[CONF_PRODUCTION_ENTITY]
    grid_entity = entry.data[CONF_GRID_ENTITY]
    battery_entity = entry.data[CONF_BATTERY_ENTITY]
    interval_hours = int(entry.data[CONF_UPDATE_INTERVAL])
    api_key = entry.data[CONF_API_KEY]

    async def _send_data(_now=None):
        prod_state = hass.states.get(production_entity)
        grid_state = hass.states.get(grid_entity)
        bat_state = hass.states.get(battery_entity)

        if not all([prod_state, grid_state, bat_state]):
            _LOGGER.warning("One or more entities not available")
            return

        now = dt_util.utcnow()
        start = _bucket_start(now - timedelta(hours=interval_hours))

        prod_history = await _get_history(hass, start, now, production_entity)
        grid_history = await _get_history(hass, start, now, grid_entity)
        bat_history = await _get_history(hass, start, now, battery_entity)

        import_history, export_history = _split_signed(grid_history)
        add_bat_history, out_bat_history = _split_signed(bat_history)

        grid_unit = grid_state.attributes.get("unit_of_measurement", "")
        bat_unit = bat_state.attributes.get("unit_of_measurement", "")

        payload = {
            "api_key": api_key,
            "production_entity": production_entity,
            "production_unit": prod_state.attributes.get("unit_of_measurement", ""),
            "production_history": prod_history,
            "import_unit": grid_unit,
            "import_history": import_history,
            "export_unit": grid_unit,
            "export_history": export_history,
            "add_battery_unit": bat_unit,
            "add_battery_history": add_bat_history,
            "out_battery_unit": bat_unit,
            "out_battery_history": out_bat_history,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        _LOGGER.debug(
                            "History sent: %d prod, %d grid, %d bat points",
                            len(prod_history),
                            len(grid_history),
                            len(bat_history),
                        )
                    else:
                        body = await resp.text()
                        _LOGGER.error("API error %s: %s", resp.status, body)
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to send data: %s", err)

    unsub = async_track_time_interval(
        hass,
        _send_data,
        timedelta(hours=interval_hours),
    )

    entry.async_on_unload(unsub)

    await _send_data()

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    return True
