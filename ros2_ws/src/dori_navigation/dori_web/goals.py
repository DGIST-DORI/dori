"""Persistent named map locations. All mutations run on the ROS executor."""

import hashlib
import json
import os
from pathlib import Path
import uuid


def map_key(signature):
    return (
        hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:24]
        if signature
        else None
    )


class GoalStore:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {"version": 1, "maps": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data.get("version") != 1 or not isinstance(
                self.data.get("maps"), dict
            ):
                raise ValueError("Invalid named-goal file")

    def list(self, key):
        return [dict(g) for g in self.data["maps"].get(key, [])] if key else []

    def get(self, key, identifier):
        for goal in self.list(key):
            if goal["id"] == identifier:
                return goal
        raise ValueError("The destination is not available on the current map.")

    def save(self, key, name, pose, identifier=None):
        if not key:
            raise ValueError("Load a map before saving a destination.")
        if not isinstance(name, str):
            raise ValueError("Enter a destination name.")
        name = " ".join(name.split())
        if not 1 <= len(name) <= 48 or any(ord(c) < 32 for c in name):
            raise ValueError("Use a name between 1 and 48 characters.")
        goals = self.list(key)
        if identifier is not None:
            self.get(key, identifier)
        if any(
            g["name"].casefold() == name.casefold() and g["id"] != identifier
            for g in goals
        ):
            raise ValueError("That destination name already exists.")
        goal = dict(
            id=identifier or uuid.uuid4().hex[:12],
            name=name,
            x=pose[0],
            y=pose[1],
            yaw=pose[2],
        )
        self.replace(key, [g for g in goals if g["id"] != goal["id"]] + [goal])
        return goal

    def delete(self, key, identifier):
        self.get(key, identifier)
        self.replace(key, [g for g in self.list(key) if g["id"] != identifier])

    def replace(self, key, goals):
        data = {"version": 1, "maps": {**self.data["maps"], key: goals}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        if self.path.exists():
            self.path.with_suffix(self.path.suffix + ".bak").write_bytes(
                self.path.read_bytes()
            )
        with temporary.open("w") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.path)
        self.data = data
