"""Config flow for Victron Charge Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AC_GRID_SETPOINT_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_CONSUMPTION_ENTITY,
    CONF_GRID_CONSUMER_ENTITY,
    CONF_GRID_FEED_IN_ENERGY_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
    CONF_SAFETY_STARTUP_GRACE_SECONDS,
    CONF_SOLAR_SURPLUS_ENTITY,
    CONF_USE_SOLCAST_FORECAST,
    DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
    DOMAIN,
)

REQUIRED_ENTITY_KEYS = (
    CONF_AC_GRID_SETPOINT_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_MAX_GRID_FEED_IN_ENTITY,
)

OPTIONAL_ENTITY_KEYS = (
    CONF_GRID_CONSUMPTION_ENTITY,
    CONF_GRID_CONSUMER_ENTITY,
    CONF_GRID_FEED_IN_ENERGY_ENTITY,
    CONF_SOLAR_SURPLUS_ENTITY,
    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AC_GRID_SETPOINT_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number"),
        ),
        vol.Required(CONF_BATTERY_SOC_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_GRID_SETPOINT_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number"),
        ),
        vol.Required(CONF_EPEX_SPOT_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_MAX_GRID_FEED_IN_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number"),
        ),
        vol.Optional(CONF_GRID_CONSUMPTION_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(CONF_GRID_CONSUMER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power"),
        ),
        vol.Optional(CONF_GRID_FEED_IN_ENERGY_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Optional(CONF_SOLAR_SURPLUS_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power"),
        ),
        vol.Optional(CONF_DC_COUPLED_PV_FEED_IN_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch"),
        ),
    }
)


def _clean_entity_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop blank optional entity selectors before storing config entry data."""
    return {
        key: value
        for key, value in user_input.items()
        if key not in OPTIONAL_ENTITY_KEYS or value not in (None, "")
    }


def _validate_entities(hass: Any, user_input: dict[str, Any]) -> dict[str, str]:
    """Validate required entities and optional entities when configured."""
    errors: dict[str, str] = {}
    for key in REQUIRED_ENTITY_KEYS:
        entity_id = user_input.get(key)
        state = hass.states.get(entity_id) if entity_id else None
        if state is None:
            errors[key] = "entity_not_found"

    ram_entity = user_input.get(CONF_AC_GRID_SETPOINT_ENTITY, "")
    if not isinstance(ram_entity, str) or not ram_entity.startswith("number."):
        errors[CONF_AC_GRID_SETPOINT_ENTITY] = "number_required"
    elif ram_entity == user_input.get(CONF_GRID_SETPOINT_ENTITY):
        errors[CONF_AC_GRID_SETPOINT_ENTITY] = "distinct_setpoints"

    for key in OPTIONAL_ENTITY_KEYS:
        entity_id = user_input.get(key)
        if not entity_id:
            continue
        state = hass.states.get(entity_id)
        if state is None:
            errors[key] = "entity_not_found"

    return errors


class VictronChargeControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Victron Charge Control."""

    VERSION = 1

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add the RAM actuator without replacing the entry or stored plan."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            data = _clean_entity_data({
                **{key: value for key, value in entry.data.items() if key not in OPTIONAL_ENTITY_KEYS},
                **user_input,
            })
            errors = _validate_entities(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, {**entry.data, **(user_input or {})}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> VictronChargeControlOptionsFlow:
        """Get the options flow handler."""
        return VictronChargeControlOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step — select Victron & EPEX entities."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            errors = _validate_entities(self.hass, user_input)

            if not errors:
                return self.async_create_entry(
                    title="Victron Charge Control",
                    data=_clean_entity_data(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class VictronChargeControlOptionsFlow(OptionsFlow):
    """Handle options flow — allows changing entities after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the options — same entity selectors, pre-filled with current values."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_entities(self.hass, user_input)

            if not errors:
                # Keep user options separate from entity references.
                data_update = {
                    key: value
                    for key, value in user_input.items()
                    if key not in (CONF_SAFETY_STARTUP_GRACE_SECONDS, CONF_USE_SOLCAST_FORECAST)
                }
                # Cleared optional selectors are omitted from the submitted form.
                current_data = {
                    key: value
                    for key, value in self._config_entry.data.items()
                    if key not in OPTIONAL_ENTITY_KEYS
                }
                options = {
                    **self._config_entry.options,
                    CONF_USE_SOLCAST_FORECAST: user_input.get(
                        CONF_USE_SOLCAST_FORECAST,
                        self._config_entry.options.get(CONF_USE_SOLCAST_FORECAST, True),
                    ),
                    CONF_SAFETY_STARTUP_GRACE_SECONDS: int(
                        user_input.get(
                            CONF_SAFETY_STARTUP_GRACE_SECONDS,
                            self._config_entry.options.get(
                                CONF_SAFETY_STARTUP_GRACE_SECONDS,
                                DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
                            ),
                        )
                    ),
                }
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=_clean_entity_data({**current_data, **data_update}),
                    options=options,
                )
                # Retry failed setup even if a previous submission already saved these values.
                self.hass.config_entries.async_schedule_reload(self._config_entry.entry_id)
                return self.async_create_entry(title="", data=options)

        # Pre-fill with current values
        current = user_input if user_input is not None else self._config_entry.data
        current_options = {**self._config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AC_GRID_SETPOINT_ENTITY,
                    default=current.get(CONF_AC_GRID_SETPOINT_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number"),
                ),
                vol.Required(
                    CONF_BATTERY_SOC_ENTITY,
                    default=current.get(CONF_BATTERY_SOC_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor"),
                ),
                vol.Required(
                    CONF_GRID_SETPOINT_ENTITY,
                    default=current.get(CONF_GRID_SETPOINT_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number"),
                ),
                vol.Required(
                    CONF_EPEX_SPOT_ENTITY,
                    default=current.get(CONF_EPEX_SPOT_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor"),
                ),
                vol.Required(
                    CONF_MAX_GRID_FEED_IN_ENTITY,
                    default=current.get(CONF_MAX_GRID_FEED_IN_ENTITY, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number"),
                ),
                vol.Optional(
                    CONF_GRID_CONSUMPTION_ENTITY,
                    description={"suggested_value": current.get(CONF_GRID_CONSUMPTION_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor"),
                ),
                vol.Optional(
                    CONF_GRID_CONSUMER_ENTITY,
                    description={"suggested_value": current.get(CONF_GRID_CONSUMER_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power"),
                ),
                vol.Optional(
                    CONF_GRID_FEED_IN_ENERGY_ENTITY,
                    description={"suggested_value": current.get(CONF_GRID_FEED_IN_ENERGY_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor"),
                ),
                vol.Optional(
                    CONF_SOLAR_SURPLUS_ENTITY,
                    description={"suggested_value": current.get(CONF_SOLAR_SURPLUS_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power"),
                ),
                vol.Optional(
                    CONF_DC_COUPLED_PV_FEED_IN_ENTITY,
                    description={"suggested_value": current.get(CONF_DC_COUPLED_PV_FEED_IN_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch"),
                ),
                vol.Optional(
                    CONF_USE_SOLCAST_FORECAST,
                    default=current_options.get(CONF_USE_SOLCAST_FORECAST, True),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_SAFETY_STARTUP_GRACE_SECONDS,
                    default=current_options.get(
                        CONF_SAFETY_STARTUP_GRACE_SECONDS,
                        DEFAULT_SAFETY_STARTUP_GRACE_SECONDS,
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=600,
                        step=10,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    ),
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
