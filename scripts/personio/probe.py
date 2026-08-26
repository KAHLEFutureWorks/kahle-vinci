from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[2] / "stack" / "personio-directory"
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import ConfigError, PersonioConfig  # noqa: E402
from app.personio import PersonioClient, PersonioError  # noqa: E402
from app.policy import filter_person  # noqa: E402


def main() -> int:
    try:
        client = PersonioClient(PersonioConfig.from_env())
        assessment = client.assess_api()
        excluded = Counter({"INACTIVE": 0, "INVALID": 0})
        eligible_count = 0
        for raw_person in client.iter_people():
            person = filter_person(raw_person, assessment.mapping)
            if person is not None:
                eligible_count += 1
                continue
            _count_exclusion(raw_person, assessment.mapping, excluded)
    except (ConfigError, PersonioError):
        print("personio_probe_ok=false")
        return 1

    print("personio_probe_ok=true")
    print(f"selected_api={assessment.version}")
    print("available_field_labels=" + ",".join(assessment.field_labels))
    print("mapped_fields=" + ",".join(sorted(assessment.mapping)))
    print(f"eligible_count={eligible_count}")
    print(
        "excluded_counts="
        + ",".join(f"{kind}:{excluded[kind]}" for kind in ("INACTIVE", "INVALID"))
    )
    return 0


def _count_exclusion(raw_person: dict[str, object], mapping: dict[str, str], excluded: Counter[str]) -> None:
    status = str(raw_person.get(mapping.get("employment_status", ""), "")).strip()
    if status == "INACTIVE":
        excluded["INACTIVE"] += 1
    else:
        excluded["INVALID"] += 1


if __name__ == "__main__":
    raise SystemExit(main())
