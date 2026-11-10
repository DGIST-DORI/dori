"""Startup deadlines distinguish absent services from waiting for an initial pose."""
import math


class StartupReadiness:
    def __init__(self, timeout, started_at):
        if not math.isfinite(timeout) or not 1 <= timeout <= 600:
            raise ValueError("startup_timeout must be between 1 and 600 seconds")
        self.timeout = timeout
        self.started_at = started_at
        self.base_ready = False
        self.localized_at = None
        self.navigation_ready = False

    def update(self, now, components, *, localized, navigation_ready):
        missing = [name for name, item in components.items() if item["state"] != "ready"]
        if not missing:
            self.base_ready = True
        if localized and self.localized_at is None:
            self.localized_at = now
        if localized and navigation_ready:
            self.navigation_ready = True
        navigation = (
            {"state": "ready", "detail": "Navigation active"} if localized and navigation_ready else
            {"state": "starting", "detail": "Waiting for navigation activation or fresh localization"}
            if self.localized_at is not None else
            {"state": "waiting_initial_pose", "detail": "Set the robot's actual initial pose in the map viewer"}
        )
        errors = []
        if not self.base_ready and now - self.started_at >= self.timeout:
            errors += [f"{name}: {components[name]['detail']}" for name in missing]
        if (self.localized_at is not None and not self.navigation_ready
                and now - self.localized_at >= self.timeout):
            errors.append("navigation: activation timed out after localization became available")
        state = "failed" if errors else (
            "not_ready" if ((self.base_ready and missing)
                            or (self.navigation_ready and navigation["state"] != "ready")) else
            "starting" if missing else navigation["state"])
        return {"state": state, "elapsed_s": round(now - self.started_at, 1),
                "components": {**components, "navigation": navigation}, "errors": errors}
