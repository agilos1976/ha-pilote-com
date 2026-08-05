DOMAIN = "ha_pilote_com"

CONF_PROFILE = "profile"
CONF_PRODUCTION_ENTITY = "production_entity"
CONF_CONSUMPTION_ENTITY = "consumption_entity"
CONF_GRID_ENTITY = "grid_entity"
CONF_ADD_BATTERY_ENTITY = "add_battery_entity"
CONF_OUT_BATTERY_ENTITY = "out_battery_entity"
CONF_SOC_ENTITY = "soc_entity"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_API_KEY = "api_key"
CONF_CONSUMERS = "consumers"
CONF_BRANDS = "brands"

DEFAULT_UPDATE_INTERVAL = 15

PROFILE_SOLAR_BATTERY = "solar_battery"
PROFILE_SOLAR = "solar"
PROFILE_CONSUMPTION = "consumption"

BRAND_KEYWORDS = {
    "whatwatt": ["whatwatt"],
    "fronius": ["fronius"],
    "solaredge": ["solaredge", "solar_edge"],
    "huawei": ["huawei", "fusionsolar"],
    "enphase": ["enphase", "envoy"],
    "shelly": ["shelly"],
    "mystrom": ["mystrom"],
    "senec": ["senec"],
    "sma": ["sma_", "_sma"],
    "kostal": ["kostal", "plenticore"],
}

GRID_HINTS = ["grid", "power_in", "power_out", "net", "meter", "reseau",
              "1_7_0", "2_7_0", "16_7_0", "import", "export"]
PROD_HINTS = ["prod", "pv", "solar", "photovoltaic", "generation",
              "power_ac", "onduleur", "inverter"]
CONSO_HINTS = ["conso", "load", "house", "home", "consumption", "verbrauch"]
BAT_IN_HINTS = ["charge", "bat_in", "battery_charge", "add_bat",
                "battery_input", "bat_power_in"]
BAT_OUT_HINTS = ["discharge", "bat_out", "battery_discharge", "out_bat",
                 "battery_output", "bat_power_out"]
SOC_HINTS = ["soc", "state_of_charge", "battery_level", "bat_percent"]

API_URL = "http://carrard.ch/RomandeDynamics/api/post_data_user.php"
