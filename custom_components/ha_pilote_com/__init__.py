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
    BACKFILL_DAYS,
    BACKFILL_INTERVAL_HOURS,
    BACKFILL_MAX_RETRIES,
    CONF_API_KEY,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CONSUMERS,
    CONF_GRID_ENTITY,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    COVERAGE_API_URL,
    DOMAIN,
    LIVE_API_URL,
    LIVE_ENTITIES,
    LIVE_INTERVAL_SECONDS,
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
                delta = v_end
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
    states = await get_instance(hass).async_add_executor_job(
        state_changes_during_period,
        hass,
        start,
        now,
        entity_id,
    )
    raw = states.get(entity_id, [])
    if use_delta:
        return _delta_15min(raw, start, now)
    return _aggregate_15min(raw, start, now)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    production_entity = entry.data[CONF_PRODUCTION_ENTITY]
    grid_entity = entry.data[CONF_GRID_ENTITY]
    battery_entity = entry.data[CONF_BATTERY_ENTITY]
    battery_soc_entity = entry.data[CONF_BATTERY_SOC_ENTITY]
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
        soc_history = await _get_history(hass, start, now, battery_soc_entity)

        import_history, export_history = _split_signed(grid_history)
        add_bat_history, out_bat_history = _split_signed(bat_history)

        grid_unit = grid_state.attributes.get("unit_of_measurement", "")
        bat_unit = bat_state.attributes.get("unit_of_measurement", "")

        payload = {
            "api_key": api_key,
            "production_entity": production_entity,
            "grid_entity": grid_entity,
            "battery_entity": battery_entity,
            "battery_soc_entity": battery_soc_entity,
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
            "soc_history": soc_history,
        }

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
                state_class = c_state.attributes.get("state_class", "")
                is_counter = state_class in ("total_increasing", "total")
                c_history = await _get_history(hass, start, now, entity_id, use_delta=is_counter)
                unit = c_state.attributes.get("unit_of_measurement", "")
                _LOGGER.debug(
                    "Consumer %s: state_class=%s, is_counter=%s, unit=%s, points=%d",
                    name, state_class, is_counter, unit, len(c_history),
                )
                consumers_data.append({
                    "name": name,
                    "entity": entity_id,
                    "unit": unit,
                    "state_class": state_class,
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
                            "History sent: %d prod, %d grid, %d bat, %d consumers",
                            len(prod_history),
                            len(grid_history),
                            len(bat_history),
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

    async def _send_live(_now=None):
        entities = {}
        for entity_id in LIVE_ENTITIES:
            state = hass.states.get(entity_id)
            if state is not None:
                entities[entity_id] = str(state.state)

        soc_state = hass.states.get(battery_soc_entity)
        battery_soc = str(soc_state.state) if soc_state else ""

        payload = {
            "api_key": api_key,
            "entities": entities,
            "battery_soc": battery_soc,
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
                _LOGGER.debug(
                    "Backfill: consommateur '%s' manque %d slots",
                    c_name, len(c_missing),
                )
            missing = missing | c_missing

        if not missing:
            _LOGGER.debug("Backfill: aucun trou détecté")
            return

        actionable = sorted(
            s for s in missing if failures.get(s, 0) < BACKFILL_MAX_RETRIES
        )
        if not actionable:
            _LOGGER.debug("Backfill: tous les trous ont atteint le max de tentatives")
            return

        _LOGGER.info("Backfill: %d trous, %d à traiter", len(missing), len(actionable))

        ranges = []
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
                ranges.append((r_start, r_end))
                r_start = slot_dt
                r_end = slot_dt + timedelta(minutes=BUCKET_MINUTES)
        if r_start:
            ranges.append((r_start, r_end))

        for r_start, r_end in ranges:
            start_utc = r_start.replace(tzinfo=tz).astimezone(dt_util.UTC).replace(tzinfo=None)
            end_utc = r_end.replace(tzinfo=tz).astimezone(dt_util.UTC).replace(tzinfo=None)

            range_slots = []
            s = r_start
            while s < r_end:
                range_slots.append(s.strftime("%Y-%m-%d %H:%M:%S"))
                s += timedelta(minutes=BUCKET_MINUTES)

            try:
                prod_h = await _get_history(hass, start_utc, end_utc, production_entity)
                grid_h = await _get_history(hass, start_utc, end_utc, grid_entity)
                bat_h = await _get_history(hass, start_utc, end_utc, battery_entity)
                soc_h = await _get_history(hass, start_utc, end_utc, battery_soc_entity)

                if not prod_h and not grid_h:
                    for sl in range_slots:
                        failures[sl] = failures.get(sl, 0) + 1
                    _LOGGER.debug("Backfill: pas de données recorder pour %s→%s", r_start, r_end)
                    continue

                imp_h, exp_h = _split_signed(grid_h)
                add_h, out_h = _split_signed(bat_h)

                prod_state = hass.states.get(production_entity)
                grid_state = hass.states.get(grid_entity)
                bat_state = hass.states.get(battery_entity)

                payload = {
                    "api_key": api_key,
                    "production_entity": production_entity,
                    "grid_entity": grid_entity,
                    "battery_entity": battery_entity,
                    "battery_soc_entity": battery_soc_entity,
                    "production_unit": prod_state.attributes.get("unit_of_measurement", "") if prod_state else "",
                    "production_history": prod_h,
                    "import_unit": grid_state.attributes.get("unit_of_measurement", "") if grid_state else "",
                    "import_history": imp_h,
                    "export_unit": grid_state.attributes.get("unit_of_measurement", "") if grid_state else "",
                    "export_history": exp_h,
                    "add_battery_unit": bat_state.attributes.get("unit_of_measurement", "") if bat_state else "",
                    "add_battery_history": add_h,
                    "out_battery_unit": bat_state.attributes.get("unit_of_measurement", "") if bat_state else "",
                    "out_battery_history": out_h,
                    "soc_history": soc_h,
                }

                consumers = entry.options.get(CONF_CONSUMERS, [])
                if consumers:
                    c_data = []
                    for consumer in consumers:
                        eid = consumer["entity"]
                        c_state = hass.states.get(eid)
                        if not c_state:
                            continue
                        sc = c_state.attributes.get("state_class", "")
                        is_ctr = sc in ("total_increasing", "total")
                        c_h = await _get_history(hass, start_utc, end_utc, eid, use_delta=is_ctr)
                        c_data.append({
                            "name": consumer["name"],
                            "entity": eid,
                            "unit": c_state.attributes.get("unit_of_measurement", ""),
                            "state_class": sc,
                            "history": c_h,
                        })
                    if c_data:
                        payload["consumers"] = c_data

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                    ) as resp:
                        if resp.status == 200:
                            _LOGGER.info(
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
        timedelta(hours=interval_hours),
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

    await _send_data()

    hass.async_create_task(_backfill())

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    return True
