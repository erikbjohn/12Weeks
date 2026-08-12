"""Garmin Connect data wrapper with caching, token persistence, and graceful degradation."""

import base64
import json
import time
import logging
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _oauth2_expires_from_blob(blob):
    """OAuth2 expires_at (epoch seconds) from a garth token dump — plain-JSON
    or base64-wrapped [oauth1, oauth2] — with zero HTTP. None if unparseable."""
    if not blob:
        return None
    try:
        tok = json.loads(blob)
    except (ValueError, TypeError):
        try:
            tok = json.loads(base64.b64decode(blob))
        except Exception:
            return None
    if isinstance(tok, (list, tuple)) and len(tok) >= 2 and isinstance(tok[1], dict):
        exp = tok[1].get("expires_at")
        # Range-guard: a corrupt blob with e.g. 1e20 would make callers'
        # datetime.fromtimestamp() raise and 500 the status endpoint.
        if isinstance(exp, (int, float)) and 0 < exp < 4102444800:  # < year 2100
            return exp
        return None
    return None


def stored_oauth2_expires_at(user_id=None):
    """The stored token's OAuth2 expiry for a user (epoch), read from the DB
    blob only. Lets callers decide whether a restore would need a live OAuth2
    exchange (the auth endpoint Garmin rate-blocks for server IPs) without
    touching Garmin."""
    try:
        from models import GarminTokens
        q = GarminTokens.query
        if user_id:
            q = q.filter_by(user_id=user_id)
        row = q.first()
        return _oauth2_expires_from_blob(row.token_data) if row else None
    except Exception:
        return None


class GarminClient:
    CACHE_TTL = 900  # 15 minutes

    def __init__(self, user_id=None):
        self.api = None
        self._cache = {}
        self._connected = False
        self._mfa_client_state = None
        self._rate_limited_until = 0
        self._user_id = user_id
        self.last_restore_error = None

    @property
    def connected(self):
        return self._connected and self.api is not None

    def oauth2_expired_in_memory(self):
        """True when the live session's OAuth2 has lapsed IN PLACE — the next
        data call would silently re-run the blocked exchange instead of
        fetching data. `connected` stays True in this state (data failures
        never flip it), so callers must check this to avoid reporting a dead
        session as live (2026-08-12 outage)."""
        try:
            tok = self.api.garth.oauth2_token
            return bool(tok and tok.expired)
        except Exception:
            return False

    def try_restore_tokens(self, user_id=None, allow_expired_exchange=False):
        """Try to restore a session from saved tokens.

        Respects the 429 cooldown (a restore performs live HTTP — profile
        fetch and possibly an OAuth2 exchange) and persists any token garth
        refreshed during login, so subsequent restores skip the OAuth2
        exchange instead of hitting Garmin's auth endpoint every time.

        When the STORED OAuth2 is already expired, a restore is guaranteed to
        re-run the full exchange — the endpoint Garmin rate-blocks for server
        IPs — so by default it refuses to try. Only the autosync daemon passes
        allow_expired_exchange=True: one controlled knock per 30-min tick, in
        case Garmin ever unblocks this IP. Every other caller (page loads,
        coach chat, briefings) stays quiet until fresh tokens arrive."""
        uid = user_id or self._user_id
        if time.time() < self._rate_limited_until:
            # Rate-limited: restoring would fire live HTTP at Garmin and
            # sustain the block. Stay disconnected until the cooldown lapses.
            # Do NOT overwrite last_restore_error — keep the original failure reason.
            return False
        if not allow_expired_exchange:
            exp = stored_oauth2_expires_at(uid)
            if exp and exp < time.time():
                self.last_restore_error = ("TokenExpired: stored OAuth2 expired; "
                                           "waiting for laptop token refresh")
                return False
        log.info("DEBUG: Garmin token restore for user_id=%s", uid)  # DEBUG: remove after fix confirmed
        try:
            from models import GarminTokens
            from garminconnect import Garmin
            query = GarminTokens.query
            if uid:
                query = query.filter_by(user_id=uid)
            tokens = query.first()
            log.info("DEBUG: Garmin token restore for user_id=%s, found=%s", uid, bool(tokens))  # DEBUG: remove after fix confirmed
            if not tokens:
                self.last_restore_error = "NoTokens: no stored Garmin tokens for user"
                return False
            self.api = Garmin()
            self.api.login(tokenstore=tokens.token_data)
            self._connected = True
            self._cache = {}
            self.last_restore_error = None  # Clear on success
            if uid:
                self._user_id = uid
            # Persist the refreshed OAuth2 back to the DB. garth silently
            # refreshes an expired OAuth2 during login(tokenstore=...); without
            # saving it the stored token stays permanently stale and EVERY
            # restore repeats a full OAuth2 exchange against Garmin's auth
            # endpoint — the classic lockout-heuristic pattern.
            self.persist_tokens_if_changed()
            log.info("Garmin session restored from saved tokens (user_id=%s)", uid)
            return True
        except Exception as e:
            err = str(e)
            # Capture the error for diagnostic reporting
            self.last_restore_error = f"{type(e).__name__}: {e}"[:200]
            if "429" in err or "Too Many" in err or "rate" in err.lower():
                # Garmin rate limit during restore — back off like login() does
                # so the next caller doesn't immediately re-hammer the auth endpoint.
                self._rate_limited_until = time.time() + 900
                log.warning("Garmin rate limited during token restore (user_id=%s)", uid)
            else:
                log.warning("Failed to restore Garmin tokens: %s", e)
            self.api = None
            self._connected = False
            return False

    def persist_tokens_if_changed(self):
        """Persist garth's current dump iff it differs from the stored row.
        garth silently re-exchanges the OAuth2 mid-data-call when it lapses;
        an unpersisted refresh dies with the process, and the next boot then
        repeats the exchange against Garmin's auth endpoint — the classic
        lockout-heuristic pattern. Returns True when a new dump was written."""
        if not self.api:
            return False
        try:
            from models import GarminTokens, db
            new_dump = self.api.garth.dumps()
            uid = self._user_id
            row = (GarminTokens.query.filter_by(user_id=uid).first()
                   if uid else GarminTokens.query.first())
            if row is None or not new_dump or new_dump == row.token_data:
                return False
            row.token_data = new_dump
            row.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            log.info("Refreshed Garmin tokens persisted (user_id=%s)", uid)
            return True
        except Exception:
            log.warning("Failed to persist refreshed Garmin tokens (user_id=%s)",
                        self._user_id, exc_info=True)
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass
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
        """Return cached value or call fetcher. During a 429 cooldown NO
        request is fired — stale cache (if any) or None is returned, so a
        rate-limited account isn't hammered by every page load / coach
        message until the block escalates into a lockout."""
        log.info("DEBUG: Garmin fetch %s (user_id=%s)", key, self._user_id)  # DEBUG: remove after fix confirmed
        now = time.time()
        if key in self._cache:
            val, ts = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        if now < self._rate_limited_until:
            # Cooldown active: serve stale cache if we have it, never fetch.
            if key in self._cache:
                return self._cache[key][0]
            return None
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

    def _user_local_today(self):
        """The user's local calendar date. Server runs UTC — date.today() is
        already 'tomorrow' every Pacific evening, which made every evening
        panel/readiness/briefing query a date Garmin has no data for."""
        try:
            if self._user_id:
                from models import User
                u = User.query.get(self._user_id)
                tz = getattr(u, "timezone", None) if u else None
                if tz:
                    from utils_time import user_local_now
                    return user_local_now(tz).date()
        except Exception:
            pass
        return date.today()

    def get_today_summary(self, today=None):
        """Return a dict with all relevant metrics for today (user-local).

        `today` may be a date (preferred — pass the app's _user_today()) or an
        ISO string; defaults to the user's local date, never server-UTC.
        Sleep is keyed to the SAME day (the night ending this morning), matching
        get_wellness_for_day — the old `yesterday` key was one night stale."""
        if not self.connected:
            return None

        if today is None:
            today = self._user_local_today()
        day_iso = today.isoformat() if hasattr(today, "isoformat") else str(today)

        hrv = self._get_hrv(day_iso)
        sleep = self._get_sleep(day_iso)
        body_battery = self._get_body_battery(day_iso)
        training_readiness = self._get_training_readiness(day_iso)
        training_status = self._get_training_status(day_iso)
        stress = self._get_stress(day_iso)

        return {
            "date": day_iso,
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
        base = self._user_local_today()
        for i in range(7):
            day = (base - timedelta(days=i)).isoformat()
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
        if time.time() < self._rate_limited_until:
            # Cooldown active: an expired-OAuth2 session would make garth
            # re-run the exchange on this call, sustaining the very 429 block
            # the cooldown exists to clear (2026-08-12 outage). Stay silent.
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

    # ── Daily wellness snapshot (history persistence) ─────────────────────

    def _get_rhr(self, day):
        def fetch():
            data = self.api.get_rhr_day(day)
            try:
                vals = ((data or {}).get("allMetrics") or {}).get("metricsMap", {}) \
                    .get("WELLNESS_RESTING_HEART_RATE") or []
                v = vals[0].get("value") if vals else None
                return int(v) if v is not None else None
            except Exception:
                return None
        return self._cached(f"rhr_{day}", fetch)

    def get_wellness_for_day(self, day_iso):
        """All wellness metrics for one calendar date. Returns None for
        known-bad states (not connected / rate limited) so callers treat it as
        'fetch failed' and retry later; otherwise a dict whose per-metric
        values may be None (Garmin had nothing — safe to persist as NULL)."""
        if not self.connected:
            return None
        if time.time() < self._rate_limited_until:
            return None
        data = {
            "hrv": self._get_hrv(day_iso),
            "sleep": self._get_sleep(day_iso),
            "bodyBattery": self._get_body_battery(day_iso),
            "trainingReadiness": self._get_training_readiness(day_iso),
            "trainingStatus": self._get_training_status(day_iso),
            "stress": self._get_stress(day_iso),
            "restingHr": self._get_rhr(day_iso),
        }
        if time.time() < self._rate_limited_until:
            # A 429 hit mid-flight — partial Nones are 'fetch failed', not 'no data'
            return None
        return data
