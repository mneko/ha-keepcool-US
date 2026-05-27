"""Constants for the Keep Cool integration."""

DOMAIN = "keepcool"
PLATFORMS = ["sensor", "binary_sensor"]

# Config keys
CONF_WEATHER_ENTITY = "weather_entity"
CONF_COMFORT_TEMP = "comfort_temp"
CONF_ROOMS = "rooms"
CONF_ROOM_NAME = "name"
CONF_ROOM_FACING = "facing"
CONF_ROOM_BLIND_ENTITY = "blind_entity"
CONF_ROOM_AUTO_CONTROL = "auto_control_blinds"

# Defaults
DEFAULT_COMFORT_TEMP = 22
UPDATE_INTERVAL_MINUTES = 15

# Window directions and their compass azimuths
FACING_OPTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
FACING_AZIMUTH: dict[str, float] = {
    "N": 0, "NE": 45, "E": 90, "SE": 135,
    "S": 180, "SW": 225, "W": 270, "NW": 315,
}

# How wide an arc counts as "sun hitting the window" (degrees either side)
SUN_FACING_TOLERANCE = 67.5

# Sun must be at least this high above horizon to count as direct sun
SUN_ELEVATION_MIN = 10.0

# Cross-ventilation
CROSS_VENT_WIND_MIN_KMH = 8.0
CROSS_VENT_ROOM_TOLERANCE = 67.5
