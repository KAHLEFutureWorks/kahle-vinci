from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .config import ConfigError, ProvisioningConfig
from .learningsuite import ProvisioningError, RequestsLearningSuiteClient
from .openwebui import SQLiteOpenWebUIUserReader
from .provisioner import AcademyProvisioner
from .state import SQLiteProvisioningStateStore
from .welcome_mail import MicrosoftGraphWelcomeMailer


class CycleRunner(Protocol):
    def run_once(self) -> dict[str, int]: ...


class HeartbeatStore(Protocol):
    def record_heartbeat(self, epoch_seconds: int) -> None: ...


def run_forever(
    provisioner: CycleRunner,
    state: HeartbeatStore,
    *,
    interval_seconds: int,
    now_epoch: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
) -> None:
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        try:
            result = provisioner.run_once()
            state.record_heartbeat(int(now_epoch()))
            print(
                "academy_provisioner_cycle "
                f"completed={result['completed']} failed={result['failed']} "
                f"skipped={result['skipped']} "
                f"pending_notified={result.get('pending_notified', 0)} "
                f"pending_failed={result.get('pending_failed', 0)}",
                flush=True,
            )
        except ProvisioningError as exc:
            print(f"academy_provisioner_cycle_failed error={exc.code}", flush=True)
        except Exception:
            print("academy_provisioner_cycle_failed error=unexpected", flush=True)
        cycles += 1
        if max_cycles is None or cycles < max_cycles:
            sleep(max(60, interval_seconds))


def main() -> int:
    try:
        config = ProvisioningConfig.from_env()
    except ConfigError as exc:
        print(f"academy_provisioner_configuration_error error={exc}", flush=True)
        return 2

    state = SQLiteProvisioningStateStore(
        Path(os.getenv("LEARNINGSUITE_STATE_DB_PATH", "/state/provisioning.sqlite3"))
    )
    provisioner = AcademyProvisioner(
        SQLiteOpenWebUIUserReader(
            Path(os.getenv("OPENWEBUI_DB_PATH", "/open-webui-data/webui.db"))
        ),
        RequestsLearningSuiteClient(config.api_base_url, config.api_key),
        state,
        config.course_name,
        allowed_emails=config.allowed_emails,
        welcome_mailer=MicrosoftGraphWelcomeMailer(
            os.environ["MICROSOFT_CLIENT_TENANT_ID"],
            os.environ["MICROSOFT_CLIENT_ID"],
            os.environ["MICROSOFT_CLIENT_SECRET"],
            os.environ["VINCI_WELCOME_MAIL_SENDER"],
        ),
    )
    run_forever(provisioner, state, interval_seconds=config.interval_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
