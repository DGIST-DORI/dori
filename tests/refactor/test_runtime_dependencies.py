"""Exercise dashboard dependencies with the same isolation as ROS launch."""

import os
import subprocess
import sys
import textwrap


def test_dashboard_dependencies_without_user_site():
    result = subprocess.run(
        [
            sys.executable,
            "-s",
            "-c",
            textwrap.dedent(
                """
                import site

                import uvicorn
                from fastapi import FastAPI
                from fastapi.testclient import TestClient
                from pydantic import BaseModel

                assert not site.ENABLE_USER_SITE
                app = FastAPI()

                class Payload(BaseModel):
                    count: int

                @app.post("/echo", response_model=Payload)
                def echo(payload: Payload):
                    return payload

                with TestClient(app) as client:
                    response = client.post("/echo", json={"count": 3})
                    assert response.status_code == 200, response.text
                    assert response.json() == {"count": 3}
                    invalid = client.post("/echo", json={"count": "invalid"})
                    assert invalid.status_code == 422, invalid.text
                """
            ),
        ],
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
