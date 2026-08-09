from __future__ import annotations

import logging
from datetime import datetime, timedelta

import asyncio

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import state_changes_during_period
from homeassistant.util import dt as dt_util

from .const import (
    API_URL,
    BACKFILL_DAYS,
    BACKFILL_INTERVAL_HOURS,
    BACKFILL_MAX_RETRIES,
    CONF_API_KEY,
    CONF_BATTERY_CHARGE_POSITIVE,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CONSUMERS,
    CONF_GRID_ENTITY,
    CONF_GRID_IMPORT_POSITIVE,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_METER_BATTERY_CHARGE,
    CONF_METER_BATTERY_DISCHARGE,
    CONF_METER_EXPORT,
    CONF_METER_IMPORT,
    CONF_METER_PRODUCTION,
    CONF_PRODUCTION_ENTITY,
    CONF_SUBTRACT_ENTITIES,
    CONF_UPDATE_INTERVAL,
    COVERAGE_API_URL,
    DOMAIN,
    LIVE_API_URL,
    LIVE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

BUCKET_MINUTES = 15

type HaPiloteComConfigEntry = ConfigEntry


def _bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES, second=0, microsecond=0)


def _subtract_histories(main_history: list[dict], sub_histories: list[list[dict]]) -> list[dict]:
    """Subtract values of sub_histories from main_history, matching by timestamp."""
    if not sub_histories:
        return main_history
    sub_maps = []
    for sh in sub_histories:
        sub_maps.append({pt["timestamp"]: pt["value"] for pt in sh})
    result = []
    for pt in main_history:
        ts = pt["timestamp"]
        val = pt["value"]
        for sm in sub_maps:
            val -= sm.get(ts, 0)
        result.append({"timestamp": ts, "value": round(max(0, val), 4)})
    return result


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


def _delta_15min(states: list, period_start: datetime, period_end: datetime) -> list[dict]:
    """Calculate energy deltas per 15-min bucket for cumulative counters (total_increasing)."""
    samples = []
    for state in states:
        if state.state in ("unavailable", "unknown"):
            continue
        try:
            value = float(state.state)
        except ValueError:
            continue
        if value < 0.001:
            continue
        samples.append((state.last_updated, value))

    if not samples:
        return []

    samples.sort(key=lambda s: s[0])

    def value_at(t):
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
        v_start = value_at(bucket_dt)
        v_end = value_at(bucket_end)
        if v_start is not None and v_end is not None:
            delta = v_end - v_start
            if delta < 0:
                delta = 0
            result.append({
                "timestamp": bucket_dt.isoformat(),
                "value": round(delta, 5),
            })
        bucket_dt += timedelta(minutes=BUCKET_MINUTES)

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


async def _get_history(hass, start, now, entity_id, use_delta=False):
    query_start = start - timedelta(minutes=BUCKET_MINUTES) if use_delta else start
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        query_start,
        now,
        entity_id,
    )
    raw = states.get(entity_id, [])
    if use_delta:
        return _delta_15min(raw, start, now)
    return _aggregate_15min(raw, start, now)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _detect_counter(hass, entity_id, name):
    """Detect if entity is a cumulative counter. Result is cached in hass.data."""
    cache = hass.data.setdefault(DOMAIN, {}).setdefault("counter_cache", {})

    c_state = hass.states.get(entity_id)
    if not c_state:
        if cache.get(entity_id):
            _LOGGER.warning("Consumer %s: entity unavailable, using cached counter=True", name)
            return True, "", "", ""
        return None, "", "", ""

    sc = c_state.attributes.get("state_class", "")
    dc = c_state.attributes.get("device_class", "")
    unit = c_state.attributes.get("unit_of_measurement", "")

    if not unit and not sc and not dc:
        if cache.get(entity_id):
            _LOGGER.warning("Consumer %s: attributes empty, using cached counter=True", name)
            return True, sc, dc, unit
        _LOGGER.warning("Consumer %s: attributes not loaded, skipping", name)
        return None, sc, dc, unit

    is_counter = (
        sc in ("total_increasing", "total")
        or dc == "energy"
        or unit.lower().strip() in ("kwh", "wh")
    )

    if not is_counter and cache.get(entity_id):
        _LOGGER.warning(
            "Consumer %s: attributes say not counter (sc=%r dc=%r unit=%r) but cache says counter — forcing delta",
            name, sc, dc, unit,
        )
        is_counter = True

    if is_counter:
        cache[entity_id] = True

    return is_counter, sc, dc, unit


async def async_setup_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    production_entity = entry.data.get(CONF_PRODUCTION_ENTITY, "")
    grid_entity = entry.data[CONF_GRID_ENTITY]
    grid_import_positive = entry.data.get(CONF_GRID_IMPORT_POSITIVE, True)
    battery_entity = entry.data.get(CONF_BATTERY_ENTITY, "")
    battery_soc_entity = entry.data.get(CONF_BATTERY_SOC_ENTITY, "")
    meter_production = entry.data.get(CONF_METER_PRODUCTION, "")
    meter_import = entry.data.get(CONF_METER_IMPORT, "")
    meter_export = entry.data.get(CONF_METER_EXPORT, "")
    meter_battery_charge = entry.data.get(CONF_METER_BATTERY_CHARGE, "")
    meter_battery_discharge = entry.data.get(CONF_METER_BATTERY_DISCHARGE, "")
    battery_charge_positive = entry.data.get(CONF_BATTERY_CHARGE_POSITIVE, True)
    interval_val = int(entry.data[CONF_UPDATE_INTERVAL])
    if interval_val < 5:
        interval_td = timedelta(hours=interval_val)
    else:
        interval_td = timedelta(minutes=interval_val)
    api_key = entry.data[CONF_API_KEY]

    async def _send_data(_now=None):
        grid_state = hass.states.get(grid_entity)
        if not grid_state:
            _LOGGER.warning("Grid entity not available")
            return

        now = dt_util.utcnow()
        start = _bucket_start(now - interval_td)

        import_history = []
        export_history = []
        grid_unit = ""
        if meter_import and meter_export:
            import_history = await _get_history(hass, start, now, meter_import, use_delta=True)
            export_history = await _get_history(hass, start, now, meter_export, use_delta=True)
            if import_history or export_history:
                grid_unit = "kWh"
        if not import_history and not export_history:
            grid_history = await _get_history(hass, start, now, grid_entity)
            if not grid_import_positive:
                for pt in grid_history:
                    pt["value"] = -pt["value"]
            import_history, export_history = _split_signed(grid_history)
            grid_unit = grid_state.attributes.get("unit_of_measurement", "")

        prod_history = []
        prod_unit = ""
        if meter_production:
            prod_history = await _get_history(hass, start, now, meter_production, use_delta=True)
            if prod_history:
                prod_unit = "kWh"
        if not prod_history and production_entity:
            prod_history = await _get_history(hass, start, now, production_entity)
            prod_state = hass.states.get(production_entity)
            prod_unit = prod_state.attributes.get("unit_of_measurement", "") if prod_state else ""

        add_bat_history = []
        out_bat_history = []
        bat_unit = ""
        soc_history = []
        if meter_battery_charge and meter_battery_discharge:
            ch_history = await _get_history(hass, start, now, meter_battery_charge, use_delta=True)
            dis_history = await _get_history(hass, start, now, meter_battery_discharge, use_delta=True)
            if ch_history or dis_history:
                if battery_charge_positive:
                    add_bat_history = ch_history
                    out_bat_history = dis_history
                else:
                    add_bat_history = dis_history
                    out_bat_history = ch_history
                bat_unit = "kWh"
        if not add_bat_history and not out_bat_history and battery_entity:
            bat_history = await _get_history(hass, start, now, battery_entity)
            add_bat_history, out_bat_history = _split_signed(bat_history)
            bat_state = hass.states.get(battery_entity)
            bat_unit = bat_state.attributes.get("unit_of_measurement", "") if bat_state else ""
        if battery_soc_entity:
            soc_history = await _get_history(hass, start, now, battery_soc_entity)

        payload = {
            "api_key": api_key,
            "production_entity": production_entity,
            "grid_entity": grid_entity,
            "battery_entity": battery_entity,
            "battery_soc_entity": battery_soc_entity,
            "production_unit": prod_unit,
            "production_history": prod_history,
            "import_unit": grid_unit,
            "import_history": import_history,
            "export_unit": grid_unit,
            "export_history": export_history,
            "add_battery_unit": bat_unit,
            "add_battery_history": add_bat_history,
            "out_battery_unit": bat_unit,
            "out_battery_history": out_bat_history,
            "soc_history": soc_history,
        }

        consumers = entry.options.get(CONF_CONSUMERS, [])
        if consumers:
            consumers_data = []
            for consumer in consumers:
                entity_id = consumer["entity"]
                name = consumer["name"]
                is_counter, sc, dc, unit = _detect_counter(hass, entity_id, name)
                if is_counter is None:
                    continue
                c_history = await _get_history(hass, start, now, entity_id, use_delta=is_counter)
                subtract_ids = consumer.get(CONF_SUBTRACT_ENTITIES, [])
                if subtract_ids:
                    sub_histories = []
                    for sub_eid in subtract_ids:
                        sub_counter, _sc, _dc, _u = _detect_counter(hass, sub_eid, f"sub:{sub_eid}")
                        if sub_counter is not None:
                            sub_h = await _get_history(hass, start, now, sub_eid, use_delta=sub_counter)
                            sub_histories.append(sub_h)
                    c_history = _subtract_histories(c_history, sub_histories)
                _LOGGER.warning(
                    "Consumer %s: sc=%r dc=%r unit=%r counter=%s pts=%d first=%s subs=%d",
                    name, sc, dc, unit, is_counter, len(c_history),
                    c_history[0]["value"] if c_history else "N/A",
                    len(subtract_ids),
                )
                consumers_data.append({
                    "name": name,
                    "entity": entity_id,
                    "unit": unit,
                    "state_class": sc,
                    "category": consumer.get("category", "other"),
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
                            "History sent: %d prod, %d imp, %d exp, %d bat, %d consumers",
                            len(prod_history),
                            len(import_history),
                            len(export_history),
                            len(add_bat_history) + len(out_bat_history),
                            n_consumers,
                        )
                    else:
                        body = await resp.text()
                        _LOGGER.error("API error %s: %s", resp.status, body)
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to send data: %s", err)

    ha_url = entry.data.get(CONF_HA_URL, "")
    ha_token = entry.data.get(CONF_HA_TOKEN, "")

    latitude = hass.config.latitude
    longitude = hass.config.longitude

    live_entity_ids = [grid_entity]
    entity_config = {"grid": grid_entity}
    if production_entity:
        live_entity_ids.append(production_entity)
        entity_config["pv"] = production_entity
    if battery_entity:
        live_entity_ids.append(battery_entity)
        entity_config["batPower"] = battery_entity
    if battery_soc_entity:
        live_entity_ids.append(battery_soc_entity)
        entity_config["soc"] = battery_soc_entity

    async def _send_live(_now=None):
        entities = {}
        for entity_id in live_entity_ids:
            state = hass.states.get(entity_id)
            if state is not None:
                entities[entity_id] = str(state.state)

        payload = {
            "api_key": api_key,
            "entities": entities,
            "entity_config": entity_config,
            "grid_import_positive": grid_import_positive,
            "ha_url": ha_url,
            "ha_token": ha_token,
            "latitude": latitude,
            "longitude": longitude,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    LIVE_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("Live API error %s", resp.status)
        except aiohttp.ClientError:
            pass

    async def _backfill(_now=None):
        """Combler les trous des derniers jours depuis le recorder HA."""
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        failures = hass.data[DOMAIN].setdefault("backfill_failures", {})

        now = dt_util.utcnow()
        tz = dt_util.get_time_zone("Europe/Zurich")
        start = _bucket_start(now - timedelta(days=BACKFILL_DAYS))

        now_local = now.astimezone(tz)
        start_local = start.astimezone(tz)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    COVERAGE_API_URL,
                    params={
                        "api_key": api_key,
                        "from": start_local.strftime("%Y-%m-%d %H:%M:%S"),
                        "to": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("Coverage API error: %s", resp.status)
                        return
                    coverage = await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.warning("Coverage API unreachable: %s", err)
            return

        existing = set(coverage.get("slots", []))
        consumer_existing = coverage.get("consumer_slots", {})

        expected = set()
        bucket = _bucket_start(start_local.replace(tzinfo=None))
        current = _bucket_start(now_local.replace(tzinfo=None))
        while bucket < current:
            expected.add(bucket.strftime("%Y-%m-%d %H:%M:%S"))
            bucket += timedelta(minutes=BUCKET_MINUTES)

        missing = expected - existing

        consumers = entry.options.get(CONF_CONSUMERS, [])
        for consumer in consumers:
            c_name = consumer["name"]
            c_existing = set(consumer_existing.get(c_name, []))
            c_missing = expected - c_existing
            if c_missing:
                _LOGGER.warning(
                    "Backfill: consommateur '%s' manque %d slots",
                    c_name, len(c_missing),
                )
            missing = missing | c_missing

        if not missing:
            _LOGGER.warning("Backfill: aucun trou détecté")
            return

        actionable = sorted(
            s for s in missing if failures.get(s, 0) < BACKFILL_MAX_RETRIES
        )
        if not actionable:
            _LOGGER.warning("Backfill: tous les trous ont atteint le max de tentatives")
            return

        _LOGGER.warning("Backfill: %d trous, %d à traiter", len(missing), len(actionable))

        raw_ranges = []
        r_start = None
        r_end = None
        for slot_str in actionable:
            slot_dt = datetime.strptime(slot_str, "%Y-%m-%d %H:%M:%S")
            if r_start is None:
                r_start = slot_dt
                r_end = slot_dt + timedelta(minutes=BUCKET_MINUTES)
            elif slot_dt == r_end:
                r_end = slot_dt + timedelta(minutes=BUCKET_MINUTES)
            else:
                raw_ranges.append((r_start, r_end))
                r_start = slot_dt
                r_end = slot_dt + timedelta(minutes=BUCKET_MINUTES)
        if r_start:
            raw_ranges.append((r_start, r_end))

        max_chunk = timedelta(hours=24)
        ranges = []
        for r_s, r_e in raw_ranges:
            while r_s < r_e:
                chunk_end = min(r_s + max_chunk, r_e)
                ranges.append((r_s, chunk_end))
                r_s = chunk_end

        _LOGGER.warning("Backfill: %d tranches à envoyer", len(ranges))

        for idx, (r_start, r_end) in enumerate(ranges):
            if idx > 0:
                await asyncio.sleep(5)
            start_utc = r_start.replace(tzinfo=tz).astimezone(dt_util.UTC)
            end_utc = r_end.replace(tzinfo=tz).astimezone(dt_util.UTC)

            range_slots = []
            s = r_start
            while s < r_end:
                range_slots.append(s.strftime("%Y-%m-%d %H:%M:%S"))
                s += timedelta(minutes=BUCKET_MINUTES)

            try:
                imp_h = []
                exp_h = []
                bf_grid_unit = ""
                if meter_import and meter_export:
                    imp_h = await _get_history(hass, start_utc, end_utc, meter_import, use_delta=True)
                    exp_h = await _get_history(hass, start_utc, end_utc, meter_export, use_delta=True)
                    if imp_h or exp_h:
                        bf_grid_unit = "kWh"
                if not imp_h and not exp_h:
                    grid_h = await _get_history(hass, start_utc, end_utc, grid_entity)
                    if not grid_import_positive:
                        for pt in grid_h:
                            pt["value"] = -pt["value"]
                    imp_h, exp_h = _split_signed(grid_h)
                    grid_state = hass.states.get(grid_entity)
                    bf_grid_unit = grid_state.attributes.get("unit_of_measurement", "") if grid_state else ""

                prod_h = []
                bf_prod_unit = ""
                if meter_production:
                    prod_h = await _get_history(hass, start_utc, end_utc, meter_production, use_delta=True)
                    if prod_h:
                        bf_prod_unit = "kWh"
                if not prod_h and production_entity:
                    prod_h = await _get_history(hass, start_utc, end_utc, production_entity)
                    prod_state = hass.states.get(production_entity)
                    bf_prod_unit = prod_state.attributes.get("unit_of_measurement", "") if prod_state else ""

                add_h = []
                out_h = []
                bf_bat_unit = ""
                soc_h = []
                if meter_battery_charge and meter_battery_discharge:
                    ch_h = await _get_history(hass, start_utc, end_utc, meter_battery_charge, use_delta=True)
                    dis_h = await _get_history(hass, start_utc, end_utc, meter_battery_discharge, use_delta=True)
                    if ch_h or dis_h:
                        if battery_charge_positive:
                            add_h = ch_h
                            out_h = dis_h
                        else:
                            add_h = dis_h
                            out_h = ch_h
                        bf_bat_unit = "kWh"
                if not add_h and not out_h and battery_entity:
                    bat_h = await _get_history(hass, start_utc, end_utc, battery_entity)
                    add_h, out_h = _split_signed(bat_h)
                    bat_state = hass.states.get(battery_entity)
                    bf_bat_unit = bat_state.attributes.get("unit_of_measurement", "") if bat_state else ""
                if battery_soc_entity:
                    soc_h = await _get_history(hass, start_utc, end_utc, battery_soc_entity)

                if not imp_h and not exp_h:
                    for sl in range_slots:
                        failures[sl] = failures.get(sl, 0) + 1
                    _LOGGER.warning("Backfill: pas de données recorder pour %s→%s", r_start, r_end)
                    continue

                payload = {
                    "api_key": api_key,
                    "production_entity": production_entity,
                    "grid_entity": grid_entity,
                    "battery_entity": battery_entity,
                    "battery_soc_entity": battery_soc_entity,
                    "production_unit": bf_prod_unit,
                    "production_history": prod_h,
                    "import_unit": bf_grid_unit,
                    "import_history": imp_h,
                    "export_unit": bf_grid_unit,
                    "export_history": exp_h,
                    "add_battery_unit": bf_bat_unit,
                    "add_battery_history": add_h,
                    "out_battery_unit": bf_bat_unit,
                    "out_battery_history": out_h,
                    "soc_history": soc_h,
                }

                consumers = entry.options.get(CONF_CONSUMERS, [])
                if consumers:
                    c_data = []
                    for consumer in consumers:
                        eid = consumer["entity"]
                        c_name = consumer["name"]
                        is_ctr, sc, dc, c_unit = _detect_counter(hass, eid, c_name)
                        if is_ctr is None:
                            continue
                        c_h = await _get_history(hass, start_utc, end_utc, eid, use_delta=is_ctr)
                        sub_ids = consumer.get(CONF_SUBTRACT_ENTITIES, [])
                        if sub_ids:
                            sub_hs = []
                            for sub_eid in sub_ids:
                                s_ctr, _sc2, _dc2, _u2 = _detect_counter(hass, sub_eid, f"sub:{sub_eid}")
                                if s_ctr is not None:
                                    sub_hs.append(await _get_history(hass, start_utc, end_utc, sub_eid, use_delta=s_ctr))
                            c_h = _subtract_histories(c_h, sub_hs)
                        c_data.append({
                            "name": c_name,
                            "entity": eid,
                            "unit": c_unit,
                            "state_class": sc,
                            "category": consumer.get("category", "other"),
                            "history": c_h,
                        })
                    if c_data:
                        payload["consumers"] = c_data

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                    ) as resp:
                        if resp.status == 200:
                            _LOGGER.warning(
                                "Backfill OK: %s → %s (%d points)",
                                r_start, r_end, len(prod_h),
                            )
                        else:
                            body = await resp.text()
                            _LOGGER.error("Backfill API error %s: %s", resp.status, body)

            except Exception as err:
                _LOGGER.error("Backfill error %s→%s: %s", r_start, r_end, err)

    unsub_history = async_track_time_interval(
        hass,
        _send_data,
        interval_td,
    )

    unsub_live = async_track_time_interval(
        hass,
        _send_live,
        timedelta(seconds=LIVE_INTERVAL_SECONDS),
    )

    unsub_backfill = async_track_time_interval(
        hass,
        _backfill,
        timedelta(hours=BACKFILL_INTERVAL_HOURS),
    )

    entry.async_on_unload(unsub_history)
    entry.async_on_unload(unsub_live)
    entry.async_on_unload(unsub_backfill)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def _delayed_start():
        await asyncio.sleep(60)
        await _send_data()
        await _backfill()

    hass.async_create_task(_delayed_start())

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    return True
