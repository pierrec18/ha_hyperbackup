"""Config flow HyperBackup — auth DSM directe avec support MFA DSM 7.3+."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigEntry
from homeassistant.const import (
    CONF_HOST, CONF_PASSWORD, CONF_PORT,
    CONF_SSL, CONF_USERNAME, CONF_VERIFY_SSL,
)

from .const import DOMAIN
from .dsm_client import SynologyDSMClient, DSMAuthRequired, DSMAuthFailed, DSMAPIError

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_ID = "device_id"
CONF_DEVICE_TOKEN = "device_token"

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Optional(CONF_PORT, default=5001): vol.Coerce(int),
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Optional(CONF_SSL, default=True): bool,
    vol.Optional(CONF_VERIFY_SSL, default=False): bool,
})

STEP_2SA_SCHEMA = vol.Schema({
    vol.Required("otp_code"): str,
})


class HyperBackupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow HyperBackup."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._otp_token: str = ""
        self._client: SynologyDSMClient | None = None

    def _make_client(self) -> SynologyDSMClient:
        ui = self._user_input
        return SynologyDSMClient(
            host=ui[CONF_HOST],
            port=ui[CONF_PORT],
            username=ui[CONF_USERNAME],
            password=ui[CONF_PASSWORD],
            use_ssl=ui.get(CONF_SSL, True),
            verify_ssl=ui.get(CONF_VERIFY_SSL, False),
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Étape 1 : credentials DSM."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_input = user_input
            client = self._make_client()
            try:
                await client.login()
                return await self._finalize(client)
            except DSMAuthRequired as exc:
                self._otp_token = exc.otp_token
                self._client = client
                return await self.async_step_2sa()
            except DSMAuthFailed:
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Erreur login : %s", err)
                errors["base"] = "unknown"
            await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_2sa(self, user_input: dict[str, Any] | None = None):
        """Étape 2 : code OTP MFA."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = self._client or self._make_client()
            try:
                await client.login(
                    otp_code=user_input["otp_code"],
                    otp_token=self._otp_token,
                )
                return await self._finalize(client)
            except DSMAuthRequired as exc:
                self._otp_token = exc.otp_token
                errors["base"] = "otp_failed"
            except DSMAuthFailed:
                errors["base"] = "otp_failed"
            except Exception as err:
                _LOGGER.exception("Erreur OTP : %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="2sa",
            data_schema=STEP_2SA_SCHEMA,
            errors=errors,
            description_placeholders={
                "username": self._user_input.get(CONF_USERNAME, ""),
            },
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Ré-authentification demandée par HA (MFA expiré)."""
        self._user_input = dict(entry_data)
        # Étape 1 : on obtient d'abord un token JWT frais
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        """
        Flux reauth en deux passes :
        - Passe A (user_input=None) : login → obtient token JWT → affiche form OTP
        - Passe B (user_input avec otp_code) : soumet OTP avec token JWT
        """
        errors: dict[str, str] = {}

        if user_input is None:
            # Passe A : lance le login pour obtenir le token JWT
            client = self._make_client()
            try:
                await client.login()
                # Pas de MFA → mise à jour directe
                return await self._update_entry(client)
            except DSMAuthRequired as exc:
                self._otp_token = exc.otp_token
                self._client = client
                # Affiche le formulaire OTP
            except Exception as err:
                _LOGGER.exception("Erreur reauth : %s", err)
                await client.close()
                errors["base"] = "unknown"
        else:
            # Passe B : soumet le code OTP
            client = self._client or self._make_client()
            try:
                await client.login(
                    otp_code=user_input["otp_code"],
                    otp_token=self._otp_token,
                )
                return await self._update_entry(client)
            except DSMAuthRequired as exc:
                self._otp_token = exc.otp_token
                errors["base"] = "otp_failed"
            except DSMAuthFailed:
                errors["base"] = "otp_failed"
            except Exception as err:
                _LOGGER.exception("Erreur reauth OTP : %s", err)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_2SA_SCHEMA,
            errors=errors,
            description_placeholders={
                "username": self._user_input.get(CONF_USERNAME, ""),
            },
        )

    async def _finalize(self, client: SynologyDSMClient):
        """Vérifie l'accès HyperBackup et crée la config entry."""
        try:
            tasks = await client.list_backup_tasks()
            _LOGGER.info("HyperBackup setup OK : %d tâche(s)", len(tasks))
        except DSMAPIError as err:
            _LOGGER.error("API HyperBackup inaccessible : %s", err)
            await client.close()
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_SCHEMA,
                errors={"base": "cannot_connect"},
            )

        data = {
            **self._user_input,
            CONF_DEVICE_ID: client.device_id,
            CONF_DEVICE_TOKEN: client.device_token,
        }
        await client.close()
        host = self._user_input.get(CONF_HOST, "NAS")
        return self.async_create_entry(title=f"HyperBackup ({host})", data=data)

    async def _update_entry(self, client: SynologyDSMClient):
        """Met à jour la config entry existante après ré-auth."""
        reauth_entry = self._get_reauth_entry()
        new_data = {
            **reauth_entry.data,
            CONF_DEVICE_ID: client.device_id,
            CONF_DEVICE_TOKEN: client.device_token,
        }
        await client.close()
        self.hass.config_entries.async_update_entry(reauth_entry, data=new_data)
        await self.hass.config_entries.async_reload(reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")
