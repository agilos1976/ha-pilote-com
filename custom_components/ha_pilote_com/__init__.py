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
    CONF_CONSUMPTION_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type HaPiloteComConfigEntry = ConfigEntry


def _states_to_history(states: list) -> list[dict]:
    history = []
    for state in states:
        if state.state in ("unavailable", "unknown"):
            continue
        try:
            value = float(state.state)
        except ValueError:
            continue
        history.append({
            "timestamp": state.last_updated.isoformat(),
            "value": value,
        })
    return history


async def async_setup_entry(
    hass: HomeAssistant, entry: HaPiloteComConfigEntry
) -> bool:
    production_entity = entry.data[CONF_PRODUCTION_ENTITY]
    consumption_entity = entry.data[CONF_CONSUMPTION_ENTITY]
    interval_hours = int(entry.data[CONF_UPDATE_INTERVAL])
    api_key = entry.data[CONF_API_KEY]

    async def _send_data(_now=None):
        prod_state = hass.states.get(production_entity)
        conso_state = hass.states.get(consumption_entity)

        if prod_state is None or conso_state is None:
            _LOGGER.warning(
                "Entity not available: production=%s, consumption=%s",
                prod_state,
                conso_state,
            )
            return

        now = dt_util.utcnow()
        start = now - timedelta(hours=interval_hours)

        history = await get_instance(hass).async_add_executor_job(
            state_changes_during_period,
            hass,
            start,
            now,
            None,
            [production_entity, consumption_entity],
        )

        prod_history = _states_to_history(history.get(production_entity, []))
        conso_history = _states_to_history(history.get(consumption_entity, []))

        payload = {
            "api_key": api_key,
            "production_entity": production_entity,
            "production_unit": prod_state.attributes.get("unit_of_measurement", ""),
            "production_history": prod_history,
            "consumption_entity": consumption_entity,
            "consumption_unit": conso_state.attributes.get("unit_of_measurement", ""),
            "consumption_history": conso_history,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        _LOGGER.debug(
                            "History sent: %d prod, %d conso points",
                            len(prod_history),
                            len(conso_history),
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
