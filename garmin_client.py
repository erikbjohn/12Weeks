"""Garmin Connect data wrapper with caching, token persistence, and graceful degradation."""

import time
import logging
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)


class GarminClient:
    CACHE_TTL = 900  # 15 minutes

    def __init__(self, user_id=None):
        self.api = None
        self._cache = {}
        self._connected = False
        self._mfa_client_state = None
        self._rate_limited_until = 0
        self._user_id = user_id

    @property
    def connected(self):
        return self._connected and self.api is not None

    def try_restore_tokens(self, user_id=None):
        """Try to restore a session from saved tokens."""
        uid = user_id or self._user_id
        log.info("DEBUG: Garmin token restore for user_id=%s", uid)  # DEBUG: remove after fix confirmed
        try:
            from models import GarminTokens, db
            from garminconnect import Garmin
            query = GarminTokens.query
            if uid:
                query = query.filter_by(user_id=uid)
            tokens = query.first()
            log.info("DEBUG: Garmin token restore for user_id=%s, found=%s", uid, bool(tokens))  # DEBUG: remove after fix confirmed
            if not tokens:
                return False
            self.api = Garmin()
            self.api.login(tokenstore=tokens.token_data)
            self._connected = True
            self._cache = {}
            if uid:
                self._user_id = uid
            log.info("Garmin session restored from saved tokens (user_id=%s)", uid)
            return True
        except Exception as e:
            log.warning("Failed to restore Garmin tokens: %s", e)
            self.api = None
            self._connected = False
            return False

    def _save_tokens(self):
        """Save current tokens to DB for persistence across deploys."""
        try:
            from models import GarminTokens, db
            token_data = self.api.garth.dumps()
            uid = self._user_id
            existing = GarminTokens.query.filter_by(user_id=uid).first() if uid else GarminTokens.query.first()
            if existing:
                existing.token_data = token_data
                existing.updated_at = datetime.now(timezone.utc)
            else:
                db.session.add(GarminTokens(token_data=token_data, user_id=uid))
            db.session.commit()
            log.info("Garmin tokens saved to DB (user_id=%s)", uid)
        except Exception as e:
            log.warning("Failed to save Garmin tokens: %s", e)

    def login(self, email, password, user_id=None, mfa_code=None):
        """Authenticate with Garmin Connect. Returns (success, error_msg, needs_mfa)."""
        if user_id:
            self._user_id = user_id
        log.info("DEBUG: Garmin login attempt for user_id=%s", self._user_id)  # DEBUG: remove after fix confirmed
        now = time.time()
        if now < self._rate_limited_until:
            wait = int(self._rate_limited_until - now)
            mins = wait // 60
            secs = wait % 60
            return False, f"Garmin rate limited. Try again in {mins}m {secs}s.", False

        try:
            from garminconnect import Garmin

            # MFA step 2
            if mfa_code and self.api and self._mfa_client_state:
                self.api.resume_login(self._mfa_client_state, mfa_code)
                self._mfa_client_state = None
                self._connected = True
                self._cache = {}
                self._save_tokens()
                return True, None, False

            # Step 1: initial login
            self.api = Garmin(email, password, is_cn=False, return_on_mfa=True)
            result = self.api.login()

            if isinstance(result, tuple) and len(result) == 2 and result[0] == "needs_mfa":
                self._mfa_client_state = result[1]
                return False, "MFA code required", True

            self._connected = True
            self._cache = {}
            self._save_tokens()
            return True, None, False
        except Exception as e:
            err = str(e)
            log.exception("Garmin login failed (user_id=%s): %s", self._user_id, err)
            if "429" in err or "Too Many Requests" in err or "rate" in err.lower():
                # Garmin rate limit — cooldown 15 minutes
                self._rate_limited_until = time.time() + 900
                wait = 900
                return False, f"Garmin rate limited. Try again in {wait // 60}m.", False
            if "401" in err or "Unauthorized" in err or "credentials" in err.lower():
                self.api = None
                self._connected = False
                return False, "Invalid Garmin credentials. Check your email and password.", False
            if "MFA" in err or "verification" in err.lower():
                return False, "MFA verification required. Check your authenticator app.", False
            self.api = None
            self._connected = False
            self._mfa_client_state = None
            return False, f"Garmin login error: {err[:200]}", False

    def _cached(self, key, fetcher):
        """Return cached value or call fetcher."""
        log.info("DEBUG: Garmin fetch %s (user_id=%s)", key, self._user_id)  # DEBUG: remove after fix confirmed
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
            err_str = str(e)
            if "429" in err_str or "Too Many" in err_str:
                self._rate_limited_until = time.time() + 900
                log.warning("Garmin rate limited during fetch: %s", key)
            else:
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

    # ── Activities + workouts (sync support) ──────────────────────────────

    def get_activities_between(self, start_iso, end_iso):
        """List activities between two ISO dates (inclusive). None on failure
        (caller treats None as 'fetch failed', distinct from empty list)."""
        if not self.connected:
            return None
        try:
            return self.api.get_activities_by_date(start_iso, end_iso)
        except Exception as e:
            err = str(e)
            if "429" in err or "Too Many" in err:
                self._rate_limited_until = time.time() + 900
            log.warning("Garmin activities fetch failed: %s", e)
            return None

    def upload_workout(self, workout_json):
        """Create a structured workout on Garmin Connect. Raises on failure —
        push_week records the error on the link row."""
        return self.api.upload_workout(workout_json)

    def schedule_workout(self, workout_id, date_str):
        """Schedule an uploaded workout on a calendar date (YYYY-MM-DD)."""
        return self.api.schedule_workout(workout_id, date_str)

    def delete_workout(self, workout_id):
        """Best-effort delete of a previously pushed workout (stale re-push).
        garminconnect has no delete_workout — hit the endpoint via garth."""
        try:
            self.api.garth.request(
                "DELETE", "connectapi",
                f"{self.api.garmin_workouts}/workout/{workout_id}", api=True)
            return True
        except Exception as e:
            log.warning("Garmin workout delete failed (%s): %s", workout_id, e)
            return False
