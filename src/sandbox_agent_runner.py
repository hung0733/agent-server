import os

from sandbox_agent.app import create_app


token = os.environ.get("SANDBOX_API_TOKEN")
if not token:
    raise RuntimeError("SANDBOX_API_TOKEN is required")

app = create_app(api_token=token)
