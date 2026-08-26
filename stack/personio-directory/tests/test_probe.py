from collections import Counter

from scripts.personio.probe import _count_exclusion


class RawWithoutEmploymentTypeAccess(dict[str, object]):
    def get(self, key: str, default: object = None) -> object:
        if key == "employment_type":
            raise AssertionError("employment type must not be inspected")
        return super().get(key, default)


def test_probe_does_not_inspect_or_classify_employment_type():
    excluded = Counter({"INACTIVE": 0, "INVALID": 0})
    raw = RawWithoutEmploymentTypeAccess({
        "employment_status": "ACTIVE",
        "employment_type": "EXTERNAL",
    })

    _count_exclusion(
        raw,
        {
            "employment_status": "employment_status",
            "employment_type": "employment_type",
        },
        excluded,
    )

    assert excluded == {"INACTIVE": 0, "INVALID": 1}
    assert "EXTERNAL" not in excluded
