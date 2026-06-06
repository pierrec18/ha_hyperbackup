"""Constantes pour l'intégration HyperBackup."""

DOMAIN = "hyperbackup"

# Domaine de l'intégration officielle Synology DSM
SYNOLOGY_DOMAIN = "synology_dsm"

# Intervalles de mise à jour
SCAN_INTERVAL_MINUTES = 15

# Noms des APIs DSM
API_BACKUP_TASK = "SYNO.Backup.Task"
API_BACKUP_VERSION = "SYNO.Backup.Version"

# Endpoint DSM
DSM_ENTRY_CGI = "entry.cgi"

# Clés de données
ATTR_TASK_ID = "task_id"
ATTR_TASK_NAME = "name"
ATTR_LAST_RESULT = "last_bkp_result"
ATTR_LAST_END_TIME = "last_bkp_end_time"
ATTR_LAST_BKP_TIME = "last_bkp_time"
ATTR_STATUS = "status"
ATTR_PROGRESS = "progress"

# Valeurs de résultat Hyper Backup
RESULT_DONE = "done"
RESULT_BACKING_UP = "backingup"
RESULT_ERROR = "error"
RESULT_NONE = "none"

# Clé de stockage du coordinator dans hass.data
COORDINATOR_KEY = "coordinator"
TASKS_KEY = "tasks"

# Formats de date Hyper Backup
DATE_FORMAT = "%Y/%m/%d %H:%M:%S"
