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
    CONF_ADD_BATTERY_ENTITY,
    CONF_API_KEY,
    CONF_CONSUMERS,
    CONF_CONSUMPTION_ENTITY,
    CONF_GRID_ENTITY,
    CONF_OUT_BATTERY_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_PROFILE,
    CONF_SOC_ENTITY,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

BUCKET_MINUTES = 15

type HaPiloteComConfigEntry = ConfigEntry


def _bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0)


def _aggregate_15min(states: list, period_start: datetime, period_end: datetime) -> list[dict]:
    """Moyenne pondérée par bucket — pour capteurs de puissance (W, kW)."""
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


def _aggregate_15min_energy(states: list, period_start: datetime, period_end: datetime) -> list[dict]:
    """Delta par bucket — pour compteurs cumulatifs (kWh, Wh)."""
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

    def _last_val_at(t):
        v = None
        for ts, val in samples:
            if ts <= t:
                v = val
            else:
                break
        return v

    result = []
    bucket_dt = _bucket_start(period_start)
    while bucket_dt < period_end:
        bucket_end = bucket_dt + timedelta(minutes=BUCKET_MINUTES)
        vs = _last_val_at(bucket_dt)
        ve = _last_val_at(bucket_end)
        if vs is not None and ve is not None:
            delta = round(max(0, ve - vs), 5)
            result.append({
                "timestamp": bucket_dt.isoformat(),
                "value": delta,
            })
        bucket_dt += timedelta(minutes=BUCKET_MINUTES)

    return result


def _split_grid(grid_history: list[dict]) -> tuple[list[dict], list[dict]]:
    """Sépare l'historique grid en import (positif) et export (négatif -> abs)."""
    import_history = []
    export_history = []
    for point in grid_history:
        ts = point["timestamp"]
        val = point["value"]
        if val >= 0:
            import_history.append({"timestamp": ts, "value": val})
            export_history.append({"timestamp": ts, "value": 0.0})
        else:
            import_history.append({"timestamp": ts, "value": 0.0})
            export_history.append({"timestamp": ts, "value": abs(val)})
    return import_history, export_history


def _empty_history() -> list[dict]:
    return []


async def _get_history(hass, start, now, entity_id, unit=""):
    is_energy = unit.lower() in ("kwh", "wh")
    query_start = start - timedelta(minutes=BUCKET_MINUTES) if is_energy else start
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        query_start,
        now,
        entity_id,
    )
    raw = states.get(entity_id, [])
    if is_energy:
        return _aggregate_15min_energy(raw, start, now)
    return _aggregate_15min(raw, start, now)


async def async_setup_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    grid_entity = entry.data[CONF_GRID_ENTITY]
    production_entity = entry.data.get(CONF_PRODUCTION_ENTITY, "")
    consumption_entity = entry.data.get(CONF_CONSUMPTION_ENTITY, "")
    add_battery_entity = entry.data.get(CONF_ADD_BATTERY_ENTITY, "")
    out_battery_entity = entry.data.get(CONF_OUT_BATTERY_ENTITY, "")
    soc_entity = entry.data.get(CONF_SOC_ENTITY, "")
    api_key = entry.data[CONF_API_KEY]

    interval_val = int(entry.data[CONF_UPDATE_INTERVAL])
    is_legacy = CONF_PROFILE not in entry.data
    if is_legacy and interval_val <= 24:
        interval_td = timedelta(hours=interval_val)
        history_td = timedelta(hours=interval_val)
    else:
        interval_td = timedelta(minutes=interval_val)
        history_td = timedelta(minutes=interval_val)

    async def _send_data(_now=None):
        grid_state = hass.states.get(grid_entity)
        if not grid_state:
            _LOGGER.warning("Grid entity %s not available", grid_entity)
            return

        prod_state = hass.states.get(production_entity) if production_entity else None
        conso_state = hass.states.get(consumption_entity) if consumption_entity else None
        add_bat_state = hass.states.get(add_battery_entity) if add_battery_entity else None
        out_bat_state = hass.states.get(out_battery_entity) if out_battery_entity else None

        now = dt_util.utcnow()
        start = _bucket_start(now - history_td)

        grid_unit = grid_state.attributes.get("unit_of_measurement", "")

        grid_history = await _get_history(hass, start, now, grid_entity, grid_unit)
        import_history, export_history = _split_grid(grid_history)

        if prod_state:
            prod_unit = prod_state.attributes.get("unit_of_measurement", "")
            prod_history = await _get_history(hass, start, now, production_entity, prod_unit)
        else:
            prod_history = _empty_history()
            prod_unit = ""

        if conso_state:
            conso_unit = conso_state.attributes.get("unit_of_measurement", "")
            conso_history = await _get_history(hass, start, now, consumption_entity, conso_unit)
        else:
            conso_history = _empty_history()
            conso_unit = ""

        if add_bat_state:
            add_bat_unit = add_bat_state.attributes.get("unit_of_measurement", "")
            add_bat_history = await _get_history(hass, start, now, add_battery_entity, add_bat_unit)
        else:
            add_bat_history = _empty_history()
            add_bat_unit = ""

        if out_bat_state:
            out_bat_unit = out_bat_state.attributes.get("unit_of_measurement", "")
            out_bat_history = await _get_history(hass, start, now, out_battery_entity, out_bat_unit)
        else:
            out_bat_history = _empty_history()
            out_bat_unit = ""

        payload = {
            "api_key": api_key,
            "production_entity": production_entity,
            "production_unit": prod_state.attributes.get("unit_of_measurement", "") if prod_state else "",
            "production_history": prod_history,
            "consumption_entity": consumption_entity,
            "consumption_unit": conso_state.attributes.get("unit_of_measurement", "") if conso_state else "",
            "consumption_history": conso_history,
            "import_unit": grid_unit,
            "import_history": import_history,
            "export_unit": grid_unit,
            "export_history": export_history,
            "add_battery_unit": add_bat_unit,
            "add_battery_history": add_bat_history,
            "out_battery_unit": out_bat_unit,
            "out_battery_history": out_bat_history,
        }

        if soc_entity:
            soc_state = hass.states.get(soc_entity)
            if soc_state:
                soc_history = await _get_history(hass, start, now, soc_entity)
                payload["soc_history"] = soc_history

        consumers = entry.options.get(CONF_CONSUMERS, [])
        if consumers:
            consumers_data = []
            for consumer in consumers:
                entity_id = consumer["entity"]
                name = consumer["name"]
                c_state = hass.states.get(entity_id)
                if not c_state:
                    _LOGGER.debug("Consumer entity %s not available", entity_id)
                    continue
                c_unit = c_state.attributes.get("unit_of_measurement", "")
                c_history = await _get_history(hass, start, now, entity_id, c_unit)
                consumers_data.append({
                    "name": name,
                    "entity": entity_id,
                    "unit": c_unit,
                    "history": c_history,
                })
            if consumers_data:
                payload["consumers"] = consumers_data

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        n_consumers = len(payload.get("consumers", []))
                        _LOGGER.debug(
                            "History sent: %d prod, %d conso, %d grid, %d addBat, %d outBat, %d consumers",
                            len(prod_history),
                            len(conso_history),
                            len(grid_history),
                            len(add_bat_history),
                            len(out_bat_history),
                            n_consumers,
                        )
                    else:
                        body = await resp.text()
                        _LOGGER.error("API error %s: %s", resp.status, body)
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to send data: %s", err)

    unsub = async_track_time_interval(
        hass,
        _send_data,
        interval_td,
    )

    entry.async_on_unload(unsub)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await _send_data()

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    return True
