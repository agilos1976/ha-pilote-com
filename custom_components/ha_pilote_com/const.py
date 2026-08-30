DOMAIN = "ha_pilote_com"

CONF_PRODUCTION_ENTITY = "production_entity"
CONF_GRID_ENTITY = "grid_entity"
CONF_BATTERY_ENTITY = "battery_entity"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_API_KEY = "api_key"
CONF_BATTERY_SOC_ENTITY = "battery_soc_entity"
CONF_GRID_IMPORT_POSITIVE = "grid_import_positive"
CONF_METER_PRODUCTION = "meter_production"
CONF_METER_IMPORT = "meter_import"
CONF_METER_EXPORT = "meter_export"
CONF_METER_BATTERY_CHARGE = "meter_battery_charge"
CONF_METER_BATTERY_DISCHARGE = "meter_battery_discharge"
CONF_BATTERY_CHARGE_POSITIVE = "battery_charge_positive"
CONF_HA_URL = "ha_url"
CONF_HA_TOKEN = "ha_token"
CONF_CONSUMERS = "consumers"
CONF_SUBTRACT_ENTITIES = "subtract_entities"
CONF_CONSUMER_POWER_ENTITY = "consumer_power_entity"

# --- Borne de recharge : pilotage ---
CONF_EV_SWITCH = "ev_switch"          # switch marche/arret de la borne
CONF_EV_AMPS = "ev_amps"              # number : consigne d'amperage
CONF_EV_PLUGGED = "ev_plugged"        # binary_sensor : cable branche
CONF_EV_POWER = "ev_power"            # sensor : puissance instantanee de la borne

# Marque de la borne. Le serveur decide toujours en amperes et en phases ;
# c'est le pilote de marque qui traduit cette consigne. Une borne inconnue
# reste pilotable en "generic" tant qu'elle expose un interrupteur et un
# reglage d'amperage.
CONF_EV_BRAND = "ev_brand"
EV_BRAND_NONE = "none"
EV_BRAND_GENERIC = "generic"
EV_BRAND_EASEE = "easee"
EV_BRANDS = [EV_BRAND_NONE, EV_BRAND_GENERIC, EV_BRAND_EASEE]

# Easee : une seule entite a designer, le capteur de statut. Les services
# Easee s'adressent a un appareil, que le registre donne depuis l'entite ;
# les autres entites de la borne sont sur ce meme appareil.
CONF_EV_EASEE_STATUS = "ev_easee_status"
DEFAULT_UPDATE_INTERVAL = 15

API_URL = "https://carrard.ch/pilote/api/post_data_user.php"
COVERAGE_API_URL = "https://carrard.ch/pilote/api/get_coverage.php"

BACKFILL_DAYS = 45
BACKFILL_MAX_RETRIES = 2
BACKFILL_INTERVAL_HOURS = 6

LIVE_API_URL = "https://carrard.ch/pilote/api/post_live.php"
LIVE_INTERVAL_SECONDS = 3

# Pilotage borne : le serveur decide, le plugin applique.
EV_API_URL = "https://carrard.ch/pilote/api.php"
# Cadence du timer. Le serveur renvoie poll_in (10 s en charge, 60 s au repos)
# et la boucle sort immediatement tant que l'echeance n'est pas atteinte.
EV_INTERVAL_SECONDS = 10
EV_FALLBACK_HOLD_SECONDS = 120    # maintien de la consigne si le serveur ne repond plus
EV_PHASE_SWITCH_WAIT = 30         # pause imposee par la borne lors d'une bascule mono/tri
