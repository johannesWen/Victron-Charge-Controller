"""Config flow for Victron Charge Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_EPEX_SPOT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_SETPOINT_ENTITY,
    DOMAIN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BATTERY_SOC_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_GRID_SETPOINT_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="number"),
        ),
        vol.Required(CONF_GRID_POWER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_BATTERY_POWER_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
        vol.Required(CONF_EPEX_SPOT_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"),
        ),
    }
)


class VictronChargeControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Victron Charge Control."""

    VERSION = 1

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

            # Validate that all entities exist
            for key in (
                CONF_BATTERY_SOC_ENTITY,
                CONF_GRID_SETPOINT_ENTITY,
                CONF_GRID_POWER_ENTITY,
                CONF_BATTERY_POWER_ENTITY,
                CONF_EPEX_SPOT_ENTITY,
            ):
                entity_id = user_input[key]
                state = self.hass.states.get(entity_id)
                if state is None:
                    errors[key] = "entity_not_found"

            if not errors:
                return self.async_create_entry(
                    title="Victron Charge Control",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
