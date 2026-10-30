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
from homeassistant.helpers.event import async_call_later, async_track_time_change
from .api import fetch_days
from .const import DOMAIN, STATISTIC_ID

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ['sensor']
RETRY_INTERVAL = timedelta(hours=3)

class OvakCoordinator:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.last_day = None
        self.last_m3 = None
        self._listeners = []
        self._running = False
        self._cancel_retry = None
        self._stopped = False
        self._tz = ZoneInfo(hass.config.time_zone)

    def async_add_listener(self, listener):
        self._listeners.append(listener)
        def remove():
            self._listeners.remove(listener)
        return remove

    async def refresh(self):
        if self._running:
            return None
        self._running = True
        try:
            # Never create a second series. The original history must be present.
            latest = await recorder.get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, STATISTIC_ID, False, {'sum', 'state'}
            )
            rows = latest.get(STATISTIC_ID, [])
            if not rows:
                _LOGGER.error('OVAK: initial statistics %s missing; import history first', STATISTIC_ID)
                # Retrying cannot fix a missing local prerequisite.
                return True
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
                if yesterday not in readings:
                    raise RuntimeError(
                        f'Missing daily reading (not yet published): {yesterday}'
                    )
                self.last_day = yesterday
                self.last_m3 = readings[yesterday] / 1000
                for listener in tuple(self._listeners):
                    listener()
                return True
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
            return True
        except Exception:
            _LOGGER.exception('OVAK update failed')
            return False
        finally:
            self._running = False

    async def refresh_with_retry(self, attempt_day=None):
        """Refresh and retry failures every three hours during the same day."""
        if self._stopped:
            return
        attempt_day = attempt_day or datetime.now(self._tz).date()
        if datetime.now(self._tz).date() != attempt_day:
            _LOGGER.info('OVAK: retry window for %s expired', attempt_day)
            return

        result = await self.refresh()
        if result is False:
            self._schedule_retry(attempt_day)
        elif result is True:
            self._cancel_pending_retry()

    def _schedule_retry(self, attempt_day):
        self._cancel_pending_retry()
        if self._stopped:
            return
        now = datetime.now(self._tz)
        next_attempt = now + RETRY_INTERVAL
        if next_attempt.date() != attempt_day:
            _LOGGER.warning(
                'OVAK: update failed and no retry fits before the end of %s',
                attempt_day,
            )
            return

        async def retry(_now):
            self._cancel_retry = None
            await self.refresh_with_retry(attempt_day)

        self._cancel_retry = async_call_later(
            self.hass, RETRY_INTERVAL, retry
        )
        _LOGGER.warning('OVAK: next retry scheduled for %s', next_attempt)

    def _cancel_pending_retry(self):
        if self._cancel_retry is not None:
            self._cancel_retry()
            self._cancel_retry = None

    def shutdown(self):
        """Cancel callbacks owned by the coordinator."""
        self._stopped = True
        self._cancel_pending_retry()

async def async_setup_entry(hass: HomeAssistant, entry):
    coordinator = OvakCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async def update(_now):
        await coordinator.refresh_with_retry()
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
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.shutdown()
    return result


async def async_update_options(hass: HomeAssistant, entry):
    await hass.config_entries.async_reload(entry.entry_id)
