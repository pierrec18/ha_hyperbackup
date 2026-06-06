"""
Client HTTP direct vers l'API DSM Synology.

Flux d'authentification DSM 7.3+ avec MFA :
  1. Login → code 403 + token JWT dans la réponse
  2. Login avec otp_code + token JWT → sid + device_id + device_token
  3. Reconnexions : Login avec device_id + device_token (bypass OTP)
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

AUTH_API = "SYNO.API.Auth"
BACKUP_TASK_API = "SYNO.Backup.Task"
BACKUP_VERSION_API = "SYNO.Backup.Version"

# Endpoint auth (différent de entry.cgi)
AUTH_ENDPOINT = "auth.cgi"
API_ENDPOINT = "entry.cgi"


class DSMAuthRequired(Exception):
    """OTP requis — contient le token JWT à repasser."""
    def __init__(self, message: str, otp_token: str = "") -> None:
        super().__init__(message)
        self.otp_token = otp_token


class DSMAuthFailed(Exception):
    """Authentification échouée."""


class DSMAPIError(Exception):
    """Erreur retournée par l'API DSM."""


class SynologyDSMClient:
    """Client HTTP async pour l'API DSM Synology avec support OTP/device_token."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
        verify_ssl: bool = False,
        device_id: str | None = None,
        device_token: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._device_id = device_id
        self._device_token = device_token

        self._sid: str | None = None
        self._syno_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        scheme = "https" if self._use_ssl else "http"
        return f"{scheme}://{self._host}:{self._port}/webapi"

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def device_token(self) -> str | None:
        return self._device_token

    def _ssl_context(self):
        if not self._use_ssl:
            return False
        if not self._verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, endpoint: str, params: dict) -> dict:
        """GET vers l'API DSM."""
        session = await self._get_session()
        url = f"{self.base_url}/{endpoint}"

        if self._sid:
            params["_sid"] = self._sid
        if self._syno_token:
            params["SynoToken"] = self._syno_token

        _LOGGER.debug("DSM → %s %s", url, {
            k: v for k, v in params.items() if k not in ("passwd", "password")
        })

        async with session.get(
            url, params=params,
            ssl=self._ssl_context(),
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            _LOGGER.debug("DSM ← %s", data)
            return data

    async def login(
        self,
        otp_code: str | None = None,
        otp_token: str | None = None,
    ) -> None:
        """
        Authentification DSM 7.3+ avec support MFA complet.

        Flux sans MFA :
          login() → sid direct

        Flux avec MFA (premier setup) :
          1. login() → lève DSMAuthRequired(otp_token=JWT)
          2. login(otp_code="123456", otp_token=JWT) → sid + device_id + device_token

        Flux reconnexion (après premier setup) :
          login() avec device_id + device_token → sid sans OTP
        """
        params: dict[str, Any] = {
            "api": AUTH_API,
            "version": "7",
            "method": "login",
            "account": self._username,
            "passwd": self._password,
            "session": "hyperbackup",
            "format": "sid",
        }

        # Reconnexion avec device_token (bypass OTP pour comptes 2FA)
        if self._device_id and self._device_token:
            params["device_id"] = self._device_id
            params["device_token"] = self._device_token
            params["enable_device_token"] = "yes"
            _LOGGER.debug("Login avec device_id + device_token")
        elif otp_code:
            # Validation OTP initiale : demander un device_token pour les reconnexions futures
            params["enable_device_token"] = "yes"

        # Validation OTP
        if otp_code:
            params["otp_code"] = otp_code
        if otp_token:
            params["token"] = otp_token

        result = await self._request(AUTH_ENDPOINT, params)

        if not result.get("success"):
            error = result.get("error", {})
            code = error.get("code", -1)
            errors = error.get("errors", {})

            # Code 403 = OTP requis
            if code == 403:
                jwt_token = errors.get("token", "")
                _LOGGER.info("MFA requis, token JWT reçu : %s...", jwt_token[:20])
                raise DSMAuthRequired(
                    "Two-step authentication required",
                    otp_token=jwt_token,
                )

            if code in (400, 401, 408):
                raise DSMAuthFailed(f"Credentials invalides (code {code})")

            raise DSMAuthFailed(f"Login échoué : code={code} data={result}")

        data = result["data"]
        self._sid = data.get("sid")
        self._syno_token = data.get("synotoken") or data.get("SynoToken")

        # Stocke device_id et device_token pour les reconnexions futures
        new_device_id = data.get("device_id")
        new_device_token = data.get("device_token")
        if new_device_id:
            self._device_id = new_device_id
        if new_device_token:
            self._device_token = new_device_token

        _LOGGER.info(
            "DSM login OK : sid=%s… device_id=%s device_token=%s",
            (self._sid or "")[:12],
            bool(self._device_id),
            bool(self._device_token),
        )

    async def call(
        self,
        api: str,
        method: str,
        version: int = 1,
        extra_params: dict | None = None,
    ) -> dict:
        """Appelle entry.cgi avec session active."""
        if not self._sid:
            raise DSMAuthFailed("Non authentifié")

        params: dict[str, Any] = {
            "api": api,
            "method": method,
            "version": version,
        }
        if extra_params:
            params.update(extra_params)

        result = await self._request(API_ENDPOINT, params)

        if not result.get("success"):
            error = result.get("error", {})
            code = error.get("code", -1)
            # Session expirée
            if code in (105, 106, 107, 119):
                _LOGGER.warning("Session expirée (code %d), re-login...", code)
                await self.login()
                return await self.call(api, method, version, extra_params)
            raise DSMAPIError(
                f"{api}.{method} échoué : code={code} data={result}"
            )

        return result.get("data", {})

    async def list_backup_tasks(self) -> list[dict]:
        """Liste les tâches Hyper Backup."""
        data = await self.call(
            api=BACKUP_TASK_API,
            method="list",
            version=1,
            extra_params={
                "additional": '["last_bkp_result","last_bkp_time","last_bkp_end_time"]'
            },
        )
        _LOGGER.debug("list_backup_tasks raw: %s", data)

        if isinstance(data, dict):
            # Structure DSM : {"task_list": [...]} ou {"task_info": [...]}
            tasks = data.get("task_list",
                    data.get("task_info",
                    data.get("tasks",
                    data.get("list", []))))
            _LOGGER.info("HyperBackup : %d tâche(s) trouvée(s) (clés dispo: %s)",
                         len(tasks), list(data.keys()))
            return tasks

        return data if isinstance(data, list) else []

    async def get_task_status(self, task_id: int) -> dict:
        """Progression d'une tâche en cours."""
        try:
            return await self.call(
                api=BACKUP_TASK_API,
                method="status",
                version=1,
                extra_params={"task_id": task_id},
            )
        except DSMAPIError as err:
            _LOGGER.debug("Statut tâche %d : %s", task_id, err)
            return {}

    async def get_task_result(self, task_id: int) -> dict:
        """Résultat du dernier backup d'une tâche."""
        try:
            return await self.call(
                api=BACKUP_TASK_API,
                method="get_result",
                version=1,
                extra_params={"task_id": task_id},
            )
        except DSMAPIError as err:
            _LOGGER.debug("Résultat tâche %d : %s", task_id, err)
            return {}

    async def get_last_successful_version(self, task_id: int) -> dict | None:
        """Dernière version réussie d'une tâche."""
        try:
            data = await self.call(
                api=BACKUP_VERSION_API,
                method="list",
                version=2,
                extra_params={"task_id": task_id},
            )
            versions = data.get("version_info_list", [])
            successful = [v for v in versions if v.get("status") == "success"]
            if not successful:
                return None
            successful.sort(key=lambda v: int(v.get("version_id", 0)), reverse=True)
            return successful[0]
        except DSMAPIError as err:
            _LOGGER.debug("Versions tâche %d : %s", task_id, err)
            return None
