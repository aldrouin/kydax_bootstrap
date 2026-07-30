"""Constants for the Kydax Bootstrap integration."""

DOMAIN = "kydax_bootstrap"

# options keys
CONF_BUNDLE = "bundle"
CONF_PROVISIONING = "provisioning"

# provisioning phases, in order; failures become "error:<phase>"
PHASE_HOLD = "hold"  # wizard finished but "start now" was unchecked
PHASE_PENDING = "pending"
PHASE_INSTALL = "install_components"
PHASE_RESTART = "restart_pending"
PHASE_ENTRIES = "create_entries"
PHASE_DASHBOARD = "build_dashboard"
PHASE_FINAL_RESTART = "final_restart_pending"
PHASE_DONE = "done"

ERROR_PREFIX = "error:"

# where plugin assets and the dashboard background live, under config/www
WWW_SUBDIR = "kydax"

# auto-update window, aligned with the historical kydax_light behaviour
AUTO_UPDATE_HOUR = 4
AUTO_UPDATE_WINDOW_MIN = 10
CRITICAL_MARKER = "[critical]"

# seconds between the restart notification and the restart itself
RESTART_DELAY_S = 10

GITHUB_API = "https://api.github.com"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal for entity state refreshes."""
    return f"{DOMAIN}_{entry_id}_update"
