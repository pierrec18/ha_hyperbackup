"""Intégration HyperBackup — connexion directe DSM."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD,
    CONF_SSL, CONF_VERIFY_SSL, Platform,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, COORDINATOR_KEY
from .coordinator import HyperBackupCoordinator
from .dsm_client import SynologyDSMClient, DSMAuthRequired, DSMAuthFailed
from .config_flow import CONF_DEVICE_ID, CONF_DEVICE_TOKEN

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass, entry: ConfigEntry) -> bool:
    """Setup de l'intégration HyperBackup."""
    hass.data.setdefault(DOMAIN, {})

    client = SynologyDSMClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        use_ssl=entry.data.get(CONF_SSL, True),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, False),
        device_id=entry.data.get(CONF_DEVICE_ID),
        device_token=entry.data.get(CONF_DEVICE_TOKEN),
    )

    try:
        await client.login()
    except DSMAuthRequired:
        # MFA requis et pas de device_token valide → demande ré-auth à l'utilisateur
        await client.close()
        raise ConfigEntryAuthFailed(
            "Two-step authentication required — please re-authenticate"
        )
    except DSMAuthFailed as err:
        await client.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        await client.close()
        raise ConfigEntryNotReady(f"Connexion DSM impossible : {err}") from err

    coordinator = HyperBackupCoordinator(hass, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await client.close()
        raise ConfigEntryNotReady(f"Premier refresh échoué : {err}") from err

    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR_KEY: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("HyperBackup initialisé avec %d tâche(s)", len(coordinator.data))
    return True


async def async_unload_entry(hass, entry: ConfigEntry) -> bool:
    """Décharge l'intégration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        coordinator = entry_data.get(COORDINATOR_KEY)
        if coordinator:
            await coordinator.client.close()
    return unload_ok
