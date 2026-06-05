from __future__ import annotations

import logging
import traceback

from nodeseek_signin.app import NodeSeekSignInApp


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )


def main() -> int:
    configure_logging()
    try:
        success = NodeSeekSignInApp().run()
    except KeyboardInterrupt:
        logging.info("User interrupted")
        return 1
    except Exception as exc:
        logging.error("Execution exception: %s", exc)
        logging.debug(traceback.format_exc())
        return 1

    return 0 if success > 0 else 1
