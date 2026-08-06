"""Environment-configured Uvicorn entrypoint."""

import uvicorn

from settings import SETTINGS


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=SETTINGS.backend_host,
        port=SETTINGS.backend_port,
        log_config=None,
    )
