DOMAIN = "ha_pilote_com"

CONF_PRODUCTION_ENTITY = "production_entity"
CONF_GRID_ENTITY = "grid_entity"
CONF_BATTERY_ENTITY = "battery_entity"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_API_KEY = "api_key"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_HA_URL = "ha_url"
CONF_HA_TOKEN = "ha_token"
CONF_CONSUMERS = "consumers"

DEFAULT_UPDATE_INTERVAL = 1

API_URL = "https://carrard.ch/pilote/api/post_data_user.php"
COVERAGE_API_URL = "https://carrard.ch/pilote/api/get_coverage.php"

BACKFILL_DAYS = 7
BACKFILL_MAX_RETRIES = 2
BACKFILL_INTERVAL_HOURS = 6

LIVE_API_URL = "https://carrard.ch/pilote/api/post_live.php"
LIVE_INTERVAL_SECONDS = 3
LIVE_ENTITIES = [
    "sensor.batteries_puissance_reelle",
    "sensor.shellypro3em_8c4f00c53adc_total_active_power",
    "sensor.energie_restante_bat",
    "sensor.batteries_soc",
    "sensor.production_energie_maison",
    "sensor.audi_q4_sportback_e_tron_primary_engine_percent",
    "binary_sensor.audi_q4_sportback_e_tron_plug_state",
    "sensor.audi_a6_avant_e_tron_primary_engine_percent",
    "binary_sensor.audi_a6_avant_e_tron_plug_state",
    "sensor.charger_status_connector_2",
    "number.charger_maximum_current",
    "sensor.charger_energy_session_2",
    "input_select.mode_batteries",
]
