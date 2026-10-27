"""
Market Bias Platform — Central Plugin Registry

Auto-discovers and manages all plugins:
  - Data plugins  (plugins/data/)
  - AI plugins    (plugins/ai/)
  - Utility plugins (plugins/util/)

Usage:
    registry = PluginRegistry.get()
    registry.data_plugins           # all data plugins
    registry.get_plugin("fred")     # by name
    registry.health_check_all()     # run health checks
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from datetime import datetime
from typing import Optional

from plugins.data.base import DataPlugin, HealthStatus, PluginType

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Singleton registry for all platform plugins.
    Automatically discovers plugins by scanning plugin packages.
    """

    _instance: Optional["PluginRegistry"] = None

    def __init__(self):
        self._data_plugins: dict[str, DataPlugin] = {}
        self._ai_plugins:   dict[str, object]     = {}
        self._discovered: bool = False

    @classmethod
    def get(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.discover()
        return cls._instance

    # ── Discovery ─────────────────────────────────────────────────────────────

    def discover(self):
        """Auto-discover all plugins by importing plugin packages."""
        self._discover_data_plugins()
        self._discover_ai_plugins()
        self._discovered = True
        logger.info(
            "Plugin registry: %d data plugins, %d AI plugins discovered",
            len(self._data_plugins), len(self._ai_plugins)
        )

    def _discover_data_plugins(self):
        """Import all modules in plugins/data/ to trigger __init_subclass__ registration."""
        try:
            import plugins.data as pkg
            for _, module_name, _ in pkgutil.iter_modules(pkg.__path__):
                if module_name == "base":
                    continue
                try:
                    importlib.import_module(f"plugins.data.{module_name}")
                except Exception as exc:
                    logger.warning("Failed to import data plugin '%s': %s", module_name, exc)
        except Exception as exc:
            logger.warning("Could not scan plugins/data: %s", exc)

        # Instantiate each registered concrete class
        for cls_name, cls in DataPlugin._registry.items():
            try:
                instance = cls()
                self._data_plugins[instance.name] = instance
                logger.debug("Registered data plugin: %s", instance.name)
            except Exception as exc:
                logger.warning("Could not instantiate %s: %s", cls_name, exc)

    def _discover_ai_plugins(self):
        """Import all modules in plugins/ai/ for AI plugin registration."""
        try:
            import plugins.ai as pkg
            for _, module_name, _ in pkgutil.iter_modules(pkg.__path__):
                if module_name == "base":
                    continue
                try:
                    importlib.import_module(f"plugins.ai.{module_name}")
                except Exception as exc:
                    logger.warning("Failed to import AI plugin '%s': %s", module_name, exc)
        except Exception as exc:
            logger.debug("No plugins/ai package found: %s", exc)

    # ── Access ────────────────────────────────────────────────────────────────

    @property
    def data_plugins(self) -> list[DataPlugin]:
        return list(self._data_plugins.values())

    @property
    def enabled_data_plugins(self) -> list[DataPlugin]:
        return [p for p in self._data_plugins.values() if p.enabled and p.is_available]

    def get_plugin(self, name: str) -> Optional[DataPlugin]:
        return self._data_plugins.get(name)

    def enable_plugin(self, name: str):
        if name in self._data_plugins:
            self._data_plugins[name].enabled = True
            self._save_status(name, enabled=True)
            logger.info("Plugin '%s' enabled", name)

    def disable_plugin(self, name: str):
        if name in self._data_plugins:
            self._data_plugins[name].enabled = False
            self._save_status(name, enabled=False)
            logger.info("Plugin '%s' disabled", name)

    # ── Health checks ─────────────────────────────────────────────────────────

    def health_check_all(self) -> dict[str, HealthStatus]:
        """Run health checks on all data plugins. Returns {name: HealthStatus}."""
        results = {}
        for name, plugin in self._data_plugins.items():
            try:
                status = plugin.health_check()
                results[name] = status
                self._save_health(name, status)
            except Exception as exc:
                status = HealthStatus(healthy=False, message=str(exc))
                results[name] = status
                self._save_health(name, status)
        return results

    def health_check_one(self, name: str) -> Optional[HealthStatus]:
        plugin = self._data_plugins.get(name)
        if plugin is None:
            return None
        status = plugin.health_check()
        self._save_health(name, status)
        return status

    # ── DB persistence ────────────────────────────────────────────────────────

    def _save_health(self, name: str, status: HealthStatus):
        try:
            from core.database import get_session
            from core.models import PluginStatus
            from sqlalchemy import select

            plugin = self._data_plugins.get(name)
            with get_session() as session:
                row = session.execute(
                    select(PluginStatus).where(PluginStatus.plugin_name == name)
                ).scalar_one_or_none()

                if row is None:
                    row = PluginStatus(
                        plugin_name=name,
                        plugin_type=plugin.plugin_type.value if plugin else None,
                    )
                    session.add(row)

                row.healthy           = status.healthy
                row.last_health_check = datetime.utcnow()
                row.health_message    = status.message
                if not status.healthy:
                    row.last_error_at  = datetime.utcnow()
                    row.last_error_msg = status.message
                    row.consecutive_errors = (row.consecutive_errors or 0) + 1
                else:
                    row.consecutive_errors = 0
                row.updated_at = datetime.utcnow()
        except Exception as exc:
            logger.debug("Could not save health status for '%s': %s", name, exc)

    def _save_status(self, name: str, enabled: bool):
        try:
            from core.database import get_session
            from core.models import PluginStatus
            from sqlalchemy import select

            with get_session() as session:
                row = session.execute(
                    select(PluginStatus).where(PluginStatus.plugin_name == name)
                ).scalar_one_or_none()
                if row:
                    row.enabled    = enabled
                    row.updated_at = datetime.utcnow()
                else:
                    session.add(PluginStatus(plugin_name=name, enabled=enabled))
        except Exception as exc:
            logger.debug("Could not save plugin status: %s", exc)

    def load_statuses_from_db(self):
        """Load enabled/disabled states from DB (called on startup)."""
        try:
            from core.database import get_session
            from core.models import PluginStatus
            from sqlalchemy import select

            with get_session() as session:
                rows = session.execute(select(PluginStatus)).scalars().all()
                statuses = {r.plugin_name: r.enabled for r in rows}

            for name, plugin in self._data_plugins.items():
                if name in statuses:
                    plugin.enabled = statuses[name]
        except Exception as exc:
            logger.debug("Could not load plugin statuses from DB: %s", exc)

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> list[dict]:
        """Returns a list of dicts for display in the Settings page."""
        result = []
        for name, plugin in self._data_plugins.items():
            h = plugin.last_health
            result.append({
                "name":         name,
                "description":  plugin.description,
                "type":         plugin.plugin_type.value,
                "enabled":      plugin.enabled,
                "available":    plugin.is_available,
                "requires_key": plugin.requires_api_key,
                "frequencies":  [f.value for f in plugin.supported_frequencies],
                "instruments":  plugin.supported_instruments[:5],  # preview
                "rate_limit_rpm": plugin.rate_limit_calls_per_minute,
                "healthy":      h.healthy if h else None,
                "health_msg":   h.message if h else "Not checked",
            })
        return result
