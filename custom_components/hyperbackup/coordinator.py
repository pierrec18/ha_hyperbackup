"""Coordinator HyperBackup."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, RESULT_BACKING_UP
from .dsm_client import SynologyDSMClient, DSMAPIError

_LOGGER = logging.getLogger(__name__)


class HyperBackupCoordinator(DataUpdateCoordinator[dict[int, dict]]):
    """Coordinator principal HyperBackup."""

    def __init__(self, hass: HomeAssistant, client: SynologyDSMClient) -> None:
        super().__init__(
            hass, _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=15),
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, dict]:
        try:
            tasks_raw = await self.client.list_backup_tasks()
        except DSMAPIError as err:
            raise UpdateFailed(f"Erreur API Hyper Backup : {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Erreur inattendue : {err}") from err

        result: dict[int, dict] = {}

        for task in tasks_raw:
            task_id = task.get("task_id")
            if task_id is None:
                continue
            task_id = int(task_id)
            enriched = dict(task)
            enriched["progress"] = None
            enriched["last_successful_version"] = None

            if task.get("last_bkp_result") == RESULT_BACKING_UP:
                status_data = await self.client.get_task_status(task_id)
                enriched["progress"] = status_data.get("progress")

            enriched["last_successful_version"] = (
                await self.client.get_last_successful_version(task_id)
            )

            result[task_id] = enriched

        return result
