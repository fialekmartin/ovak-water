"""OVAK water integration: append daily data to an existing external statistic."""
from datetime import datetime, time, timedelta
import logging
from zoneinfo import ZoneInfo
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.components import recorder
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics, get_last_statistics,
)
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from .api import fetch_days
from .const import DOMAIN, STATISTIC_ID

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ['sensor']

class OvakCoordinator:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.last_day = None
        self.last_m3 = None
        self._listeners = []
        self._running = False
        self._tz = ZoneInfo(hass.config.time_zone)

    def async_add_listener(self, listener):
        self._listeners.append(listener)
        def remove():
            self._listeners.remove(listener)
        return remove

    async def refresh(self):
        if self._running:
            return
        self._running = True
        try:
            # Never create a second series. The original history must be present.
            latest = await recorder.get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, STATISTIC_ID, False, {'sum', 'state'}
            )
            rows = latest.get(STATISTIC_ID, [])
            if not rows:
                _LOGGER.error('OVAK: initial statistics %s missing; import history first', STATISTIC_ID)
                return
            row = rows[-1]
            # The import script places each daily value at midnight of the following day.
            local = datetime.fromtimestamp(row['start'], self._tz)
            last_start = local.date()
            yesterday = datetime.now(self._tz).date() - timedelta(days=1)
            first = last_start
            if first > yesterday:
                # Still provide a daily sensor value after restart.
                readings = await self.hass.async_add_executor_job(
                    fetch_days, self.entry.data[CONF_USERNAME],
                    self.entry.data[CONF_PASSWORD], yesterday, yesterday
                )
                if yesterday in readings:
                    self.last_day = yesterday
                    self.last_m3 = readings[yesterday] / 1000
                    for listener in tuple(self._listeners):
                        listener()
                return
            # Cap catch-up request interval; repeated poll catches up over time.
            last = min(yesterday, first + timedelta(days=30))
            readings = await self.hass.async_add_executor_job(
                fetch_days, self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD], first, last
            )
            missing = [d for d in (first + timedelta(days=i) for i in range((last-first).days+1)) if d not in readings]
            if missing:
                raise RuntimeError(f'Missing daily readings (not yet published): {missing[0]}')
            total = float(row['sum'])
            state = float(row['state'])
            stats = []
            for day in sorted(readings):
                delta = readings[day] / 1000
                total = round(total + delta, 3)
                state = round(state + delta, 3)
                stats.append({
                    'start': datetime.combine(day + timedelta(days=1), time.min, self._tz),
                    'sum': total,
                    'state': state,
                })
            async_add_external_statistics(self.hass, {
                'statistic_id': STATISTIC_ID,
                'source': DOMAIN,
                'name': 'OVAK spotřeba vody',
                'unit_of_measurement': 'm³',
                'unit_class': 'volume',
                'has_sum': True,
                'mean_type': StatisticMeanType.NONE,
            }, stats)
            self.last_day = last
            self.last_m3 = readings[last] / 1000
            for listener in tuple(self._listeners):
                listener()
            _LOGGER.info('OVAK: queued %d new daily statistics through %s', len(stats), last)
        except Exception:
            _LOGGER.exception('OVAK update failed')
        finally:
            self._running = False

async def async_setup_entry(hass: HomeAssistant, entry):
    coordinator = OvakCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async def update(_now):
        await coordinator.refresh()
    sync_time = entry.options.get('sync_time', '06:00')
    selected_time = time.fromisoformat(sync_time)
    hour, minute = selected_time.hour, selected_time.minute
    entry.async_on_unload(async_track_time_change(
        hass, update, hour=hour, minute=minute, second=0
    ))
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    _LOGGER.info('OVAK: scheduled daily synchronization at %s (%s)', sync_time, hass.config.time_zone)
    return True

async def async_unload_entry(hass, entry):
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if result:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return result


async def async_update_options(hass: HomeAssistant, entry):
    await hass.config_entries.async_reload(entry.entry_id)
