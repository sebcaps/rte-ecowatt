import voluptuous as vol
import logging
from typing import Any, Optional
from oauthlib.oauth2 import rfc6749
from copy import deepcopy
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.helpers.entity_registry import (
    async_entries_for_config_entry,
    async_get_registry,
)
from .const import DOMAIN
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SENSOR_UNIT,
    CONF_SENSOR_SHIFT,
    CONF_SENSORS,
)
from . import AsyncOauthClient

_LOGGER = logging.getLogger(__name__)

# Description of the config flow:
# async_step_user is called when user starts to configure the integration
# we follow with a flow of form/menu
# eventually we call async_create_entry with a dictionnary of data
# HA calls async_setup_entry with a ConfigEntry which wraps this data (defined in __init__.py)
# in async_setup_entry we call hass.config_entries.async_setup_platforms to setup each relevant platform (sensor in our case)
# HA calls async_setup_entry from sensor.py


class SetupConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None):
        """Called once with None as user_input, then a second time with user provided input"""
        errors = {}
        valid = False

        if user_input is not None:
            _LOGGER.debug(f"User input is {user_input}")
            _LOGGER.debug("Testing connectivity to RTE api")
            try:
                test_client = AsyncOauthClient(user_input)
                await test_client.client()
                valid = True
            except rfc6749.errors.InvalidClientError:
                _LOGGER.error(
                    "Unable to validate RTE api access. Credentials are likely incorrect"
                )
                errors["base"] = "auth_error"
            except Exception as e:
                _LOGGER.error(f"Unable to validate RTE api access, unknown error: {e}")
                errors["base"] = "generic_error"
            if valid:
                _LOGGER.debug("Connectivity to RTE api validated")
                self.user_input = user_input
                if "sensors" not in self.user_input:
                    self.user_input["sensors"] = []

                return self._configuration_menu("user")

        data_schema = {
            vol.Required(CONF_CLIENT_ID): cv.string,
            vol.Required(CONF_CLIENT_SECRET): cv.string,
        }

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=errors
        )

    def _configuration_menu(self, step_id: str):
        return self.async_show_menu(
            step_id=step_id,
            menu_options=[
                "finish_configuration",
                "configure_hours_sensor",
                "configure_days_sensor",
            ],
        )

    async def async_step_finish_configuration(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        _LOGGER.info(f"Configuration from user is finished, input is {self.user_input}")
        await self.async_set_unique_id(self.user_input[CONF_CLIENT_ID])
        self._abort_if_unique_id_configured()
        # will call async_setup_entry defined in __init__.py file
        return self.async_create_entry(title="ecowatt by RTE", data=self.user_input)

    async def async_step_configure_hours_sensor(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        return self._manual_configuration_step(
            "hours", vol.In(range(4 * 24)), user_input
        )

    async def async_step_configure_days_sensor(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        return self._manual_configuration_step("days", vol.In(range(4)), user_input)

    def _manual_configuration_step(
        self, sensor_unit, validator, user_input: Optional[dict[str, Any]] = None
    ):
        step_name = f"configure_{sensor_unit}_sensor"
        errors = {}
        data_schema = {
            vol.Required(CONF_SENSOR_SHIFT): vol.All(vol.Coerce(int), validator),
        }
        if user_input is not None:
            self.user_input["sensors"].append(
                {
                    CONF_SENSOR_UNIT: sensor_unit,
                    CONF_SENSOR_SHIFT: user_input[CONF_SENSOR_SHIFT],
                }
            )
            return self._configuration_menu(step_name)

        return self.async_show_form(
            step_id=step_name,
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


# FIXME(g.seux): This class is mostly a duplicate from the SetupConfigFlow. How can we make it common
class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self.user_input = None
        self.all_sensors = None
        self.sensor_map = None
        self.entity_registry = None

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""

        if self.user_input is None:  # done once, feed user_input with existing sensors
            self.user_input: dict[
                str, Any
            ] = self.config_entry.data  # casting is a bit brutal but works
        # Grab all configured sensors from the entity registry so we can populate the
        # multi-select dropdown that will allow a user to remove a sensor.
        self.entity_registry = await async_get_registry(self.hass)
        entries = async_entries_for_config_entry(
            self.entity_registry, self.config_entry.entry_id
        )
        # Default value for our multi-select.
        self.all_sensors = {e.entity_id: e.original_name for e in entries}
        self.sensor_map = {e.entity_id: e for e in entries}
        return self._configuration_menu("init")

    def _configuration_menu(self, step_id: str):
        return self.async_show_menu(
            step_id=step_id,
            menu_options=[
                "finish_configuration",
                "configure_hours_sensor",
                "configure_days_sensor",
                "delete_sensor",
            ],
        )

    async def async_step_finish_configuration(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        _LOGGER.info(f"Configuration from user is finished, input is {self.user_input}")
        # will call async_setup_entry defined in __init__.py file
        return self.async_create_entry(title="ecowatt by RTE", data=self.user_input)

    async def async_step_configure_hours_sensor(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        return self._manual_configuration_step(
            "hours", vol.In(range(4 * 24)), user_input
        )

    async def async_step_configure_days_sensor(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        return self._manual_configuration_step("days", vol.In(range(4)), user_input)

    async def async_step_delete_sensor(
        self, user_input: Optional[dict[str, Any]] = None
    ):
        _LOGGER.info(f"User will delete on or more sensor(s)")
        _LOGGER.debug(f"User Input is :{user_input}")
        errors: Dict[str, str] = {}
        if user_input is not None:

            updated_sensor = deepcopy(self.config_entry.data[CONF_SENSORS])

            # Remove any unchecked sensor.
            removed_sensors = [
                entity_id
                for entity_id in self.sensor_map.keys()
                if entity_id not in user_input[CONF_SENSORS]
            ]
            _LOGGER.debug(f"Removed sensor is : {removed_sensors}")
            _LOGGER.debug(f"updated_sensor sensor is : {updated_sensor}")
            for entity_id in removed_sensors:
                _LOGGER.debug(f"Removed sensor entity_id is : {entity_id}")
                # Unregister from HA
                self.entity_registry.async_remove(entity_id)
                # Remove from our configured sensor.
                entry = self.sensor_map[entity_id]
                entry_path = entry.unique_id
                _LOGGER.debug(f"entry_path is : {entry_path}")
                _LOGGER.debug(f"updated_sensor is : {updated_sensor}")
                updated_sensor = [e for e in updated_sensor if e["path"] != entry_path]

        return self.async_show_form(
            step_id="delete_sensor",
            # data_schema=vol.Schema(data_schema),
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SENSORS, default=list(self.all_sensors.keys())
                    ): cv.multi_select(self.all_sensors)
                }
            ),
            errors=errors,
        )

    def _manual_configuration_step(
        self, sensor_unit, validator, user_input: Optional[dict[str, Any]] = None
    ):
        step_name = f"configure_{sensor_unit}_sensor"
        errors = {}
        data_schema = {
            vol.Required(CONF_SENSOR_SHIFT): vol.All(vol.Coerce(int), validator),
        }
        if user_input is not None:
            self.user_input["sensors"].append(
                {
                    CONF_SENSOR_UNIT: sensor_unit,
                    CONF_SENSOR_SHIFT: user_input[CONF_SENSOR_SHIFT],
                }
            )
            return self._configuration_menu(step_name)

        return self.async_show_form(
            step_id=step_name,
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )
