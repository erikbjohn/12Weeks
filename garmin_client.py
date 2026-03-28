"""Garmin Connect data wrapper with caching and graceful degradation."""

import time
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


class GarminClient:
    CACHE_TTL = 900  # 15 minutes

    def __init__(self):
        self.api = None
        self._cache = {}
        self._connected = False

    @property
    def connected(self):
        return self._connected and self.api is not None

    def login(self, email, password):
        """Authenticate with Garmin Connect. Returns (success, error_msg)."""
        try:
            from garminconnect import Garmin
            self.api = Garmin(email, password)
            self.api.login()
            self._connected = True
            self._cache = {}
            return True, None
        except Exception as e:
            log.exception("Garmin login failed")
            self.api = None
            self._connected = False
            return False, str(e)

    def _cached(self, key, fetcher):
        """Return cached value or call fetcher."""
        now = time.time()
        if key in self._cache:
            val, ts = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        try:
            val = fetcher()
            self._cache[key] = (val, now)
            return val
        except Exception as e:
            log.warning("Garmin fetch %s failed: %s", key, e)
            # Return stale cache if available
            if key in self._cache:
                return self._cache[key][0]
            return None

    def get_today_summary(self):
        """Return a dict with all relevant metrics for today."""
        if not self.connected:
            return None

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        hrv = self._get_hrv(today)
        sleep = self._get_sleep(yesterday)
        body_battery = self._get_body_battery(today)
        training_readiness = self._get_training_readiness(today)
        training_status = self._get_training_status(today)
        stress = self._get_stress(today)

        return {
            "date": today,
            "hrv": hrv,
            "sleep": sleep,
            "bodyBattery": body_battery,
            "trainingReadiness": training_readiness,
            "trainingStatus": training_status,
            "stress": stress,
        }

    def _get_hrv(self, day):
        def fetch():
            data = self.api.get_hrv_data(day)
            summary = data.get("hrvSummary", {}) if data else {}
            weekly = summary.get("weeklyAvg", None)
            last_night = summary.get("lastNightAvg", None)
            status = summary.get("status", None)
            baseline = summary.get("baseline", {})
            return {
                "lastNight": last_night,
                "weeklyAvg": weekly,
                "status": status,
                "baselineLow": baseline.get("lowUpper", None),
                "baselineHigh": baseline.get("balancedHigh", None),
            }
        return self._cached(f"hrv_{day}", fetch)

    def _get_sleep(self, day):
        def fetch():
            data = self.api.get_sleep_data(day)
            if not data:
                return None
            daily = data.get("dailySleepDTO", {})
            return {
                "durationSeconds": daily.get("sleepTimeSeconds", 0),
                "durationHours": round(daily.get("sleepTimeSeconds", 0) / 3600, 1),
                "deepSeconds": daily.get("deepSleepSeconds", 0),
                "lightSeconds": daily.get("lightSleepSeconds", 0),
                "remSeconds": daily.get("remSleepSeconds", 0),
                "awakeSeconds": daily.get("awakeSleepSeconds", 0),
                "score": daily.get("sleepScores", {}).get("overall", {}).get("value", None),
                "qualityScore": daily.get("sleepScores", {}).get("quality", {}).get("qualifierKey", None),
            }
        return self._cached(f"sleep_{day}", fetch)

    def _get_body_battery(self, day):
        def fetch():
            data = self.api.get_body_battery(day)
            if not data:
                return None
            # Body battery is a list of readings
            if isinstance(data, list) and len(data) > 0:
                latest = data[-1] if data else {}
                charged = max((d.get("charged", 0) for d in data), default=0)
                drained = max((d.get("drained", 0) for d in data), default=0)
                return {
                    "current": latest.get("charged", 0) - latest.get("drained", 0),
                    "charged": charged,
                    "drained": drained,
                }
            return {"current": None, "charged": None, "drained": None}
        return self._cached(f"bb_{day}", fetch)

    def _get_training_readiness(self, day):
        def fetch():
            data = self.api.get_training_readiness(day)
            if not data:
                return None
            return {
                "score": data.get("score", None),
                "level": data.get("level", None),
                "sleepComponent": data.get("sleepScore", None),
                "recoveryComponent": data.get("recoveryScore", None),
                "trainingLoadComponent": data.get("activityScore", None),
            }
        return self._cached(f"tr_{day}", fetch)

    def _get_training_status(self, day):
        def fetch():
            data = self.api.get_training_status(day)
            if not data:
                return None
            return {
                "status": data.get("trainingStatus", None),
                "load": data.get("weeklyTrainingLoad", None),
                "vo2max": data.get("mostRecentVO2Max", None),
            }
        return self._cached(f"ts_{day}", fetch)

    def _get_stress(self, day):
        def fetch():
            data = self.api.get_stress_data(day)
            if not data:
                return None
            overall = data.get("overallStressLevel", None)
            rest = data.get("restStressDuration", 0)
            high = data.get("highStressDuration", 0)
            return {
                "overall": overall,
                "restDuration": rest,
                "highDuration": high,
            }
        return self._cached(f"stress_{day}", fetch)

    def get_weekly_hrv(self):
        """Get 7 days of HRV for trend analysis."""
        if not self.connected:
            return None
        results = []
        for i in range(7):
            day = (date.today() - timedelta(days=i)).isoformat()
            hrv = self._get_hrv(day)
            if hrv and hrv.get("lastNight") is not None:
                results.append({"date": day, "hrv": hrv["lastNight"]})
        return results
