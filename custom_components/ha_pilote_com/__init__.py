from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

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

        payload = {
            "api_key": api_key,
            "production": prod_state.state,
            "production_unit": prod_state.attributes.get("unit_of_measurement", ""),
            "production_entity": production_entity,
            "consumption": conso_state.state,
            "consumption_unit": conso_state.attributes.get("unit_of_measurement", ""),
            "consumption_entity": consumption_entity,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        _LOGGER.debug("Data sent successfully to HA Pilote Com")
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
