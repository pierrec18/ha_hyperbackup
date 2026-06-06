"""
Entités sensor pour HyperBackup.

Crée dynamiquement pour chaque tâche Hyper Backup découverte :
  - sensor.hyperbackup_<nom>_last_backup   (timestamp dernier backup réussi)
  - sensor.hyperbackup_<nom>_result         (résultat : done / error / backingup)
  - sensor.hyperbackup_<nom>_progress       (% progression si backup en cours)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    COORDINATOR_KEY,
    ATTR_TASK_ID,
    ATTR_TASK_NAME,
    ATTR_LAST_RESULT,
    ATTR_LAST_END_TIME,
    ATTR_PROGRESS,
    DATE_FORMAT,
    RESULT_DONE,
    RESULT_BACKING_UP,
    RESULT_ERROR,
)
from .coordinator import HyperBackupCoordinator

_LOGGER = logging.getLogger(__name__)

# Icônes par résultat
RESULT_ICONS = {
    RESULT_DONE: "mdi:check-circle",
    RESULT_BACKING_UP: "mdi:cloud-sync",
    RESULT_ERROR: "mdi:alert-circle",
    None: "mdi:help-circle",
}

# Couleurs (pour les cartes Mushroom dans le dashboard)
RESULT_FRIENDLY = {
    RESULT_DONE: "Réussi",
    RESULT_BACKING_UP: "En cours",
    RESULT_ERROR: "Erreur",
    "none": "Jamais exécuté",
    None: "Inconnu",
}


def _slugify(name: str) -> str:
    """Transforme un nom de tâche en slug HA valide."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9_]", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def _parse_dsm_date(raw: str | None) -> datetime | None:
    """Parse une date DSM Hyper Backup en datetime UTC-aware."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, DATE_FORMAT)
        # Les dates DSM Hyper Backup sont en heure locale du NAS.
        # On les traite comme naïves et on leur assigne l'UTC pour HA.
        # Note : si ton NAS est en Europe/Paris, il y aura un offset de 1-2h.
        # Pour une précision absolue, un patch ultérieur pourrait lire la timezone DSM.
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        _LOGGER.debug("Impossible de parser la date HyperBackup : %r", raw)
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les entités sensor pour chaque tâche Hyper Backup découverte."""
    coordinator: HyperBackupCoordinator = hass.data[DOMAIN][entry.entry_id][
        COORDINATOR_KEY
    ]

    entities: list[SensorEntity] = []

    for task_id, task_data in coordinator.data.items():
        task_name = task_data.get(ATTR_TASK_NAME, f"task_{task_id}")
        slug = _slugify(task_name)

        _LOGGER.debug(
            "Création des entités pour la tâche %d '%s' (slug: %s)",
            task_id,
            task_name,
            slug,
        )

        entities.extend([
            HyperBackupLastBackupSensor(coordinator, task_id, task_name, slug),
            HyperBackupResultSensor(coordinator, task_id, task_name, slug),
            HyperBackupProgressSensor(coordinator, task_id, task_name, slug),
        ])

    if not entities:
        _LOGGER.warning(
            "Aucune tâche Hyper Backup trouvée — aucune entité créée. "
            "Vérifiez que Hyper Backup est installé et configuré sur le NAS."
        )

    async_add_entities(entities)


class HyperBackupBaseSensor(CoordinatorEntity[HyperBackupCoordinator], SensorEntity):
    """Classe de base pour les entités HyperBackup."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HyperBackupCoordinator,
        task_id: int,
        task_name: str,
        slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._task_name = task_name
        self._slug = slug

    @property
    def _task_data(self) -> dict:
        """Données actuelles de la tâche depuis le coordinator."""
        return self.coordinator.data.get(self._task_id, {})

    @property
    def device_info(self):
        """Regroupe les capteurs d'une même tâche sous un même device."""
        from homeassistant.helpers.device_registry import DeviceInfo
        return DeviceInfo(
            identifiers={(DOMAIN, f"task_{self._task_id}")},
            name=f"HyperBackup — {self._task_name}",
            manufacturer="Synology",
            model="Hyper Backup Task",
        )


class HyperBackupLastBackupSensor(HyperBackupBaseSensor):
    """Timestamp du dernier backup réussi."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:backup-restore"

    def __init__(self, coordinator, task_id, task_name, slug):
        super().__init__(coordinator, task_id, task_name, slug)
        self._attr_unique_id = f"hyperbackup_{task_id}_last_backup"
        self._attr_name = "Dernier backup"

    @property
    def native_value(self) -> datetime | None:
        task = self._task_data

        # Priorité 1 : last_bkp_end_time si le résultat est "done"
        if task.get(ATTR_LAST_RESULT) == RESULT_DONE:
            dt = _parse_dsm_date(task.get(ATTR_LAST_END_TIME))
            if dt:
                return dt

        # Priorité 2 : dernière version réussie via SYNO.Backup.Version
        last_version = task.get("last_successful_version")
        if last_version:
            raw = last_version.get("complete_time_local")
            dt = _parse_dsm_date(raw)
            if dt:
                return dt

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        task = self._task_data
        last_version = task.get("last_successful_version")
        return {
            "task_id": self._task_id,
            "task_name": self._task_name,
            "last_version_id": last_version.get("version_id") if last_version else None,
        }


class HyperBackupResultSensor(HyperBackupBaseSensor):
    """Résultat du dernier backup (done / error / backingup)."""

    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator, task_id, task_name, slug):
        super().__init__(coordinator, task_id, task_name, slug)
        self._attr_unique_id = f"hyperbackup_{task_id}_result"
        self._attr_name = "Résultat"

    @property
    def native_value(self) -> str:
        result = self._task_data.get(ATTR_LAST_RESULT, "unknown")
        return RESULT_FRIENDLY.get(result, result)

    @property
    def icon(self) -> str:
        result = self._task_data.get(ATTR_LAST_RESULT)
        return RESULT_ICONS.get(result, "mdi:help-circle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        task = self._task_data
        return {
            "task_id": self._task_id,
            "task_name": self._task_name,
            "raw_result": task.get(ATTR_LAST_RESULT),
            "last_bkp_end_time": task.get(ATTR_LAST_END_TIME),
        }


class HyperBackupProgressSensor(HyperBackupBaseSensor):
    """Progression en % si un backup est en cours, sinon None."""

    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, coordinator, task_id, task_name, slug):
        super().__init__(coordinator, task_id, task_name, slug)
        self._attr_unique_id = f"hyperbackup_{task_id}_progress"
        self._attr_name = "Progression"

    @property
    def native_value(self) -> int | None:
        task = self._task_data
        if task.get(ATTR_LAST_RESULT) != RESULT_BACKING_UP:
            return None
        progress = task.get(ATTR_PROGRESS)
        if not progress:
            return None
        return int(progress.get("progress", 0))

    @property
    def available(self) -> bool:
        """Disponible uniquement si un backup est en cours."""
        return self._task_data.get(ATTR_LAST_RESULT) == RESULT_BACKING_UP

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        task = self._task_data
        progress = task.get(ATTR_PROGRESS) or {}
        return {
            "task_id": self._task_id,
            "task_name": self._task_name,
            "step": progress.get("step"),
            "processed_size": progress.get("processed_size"),
            "total_size": progress.get("total_size"),
            "status": task.get("status"),
        }
