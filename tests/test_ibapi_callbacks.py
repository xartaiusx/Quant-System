import pytest

from trader.broker.ibapi_callbacks import normalize_ibkr_error_args


def test_normalizes_legacy_error_callback() -> None:
    result = normalize_ibkr_error_args((2104, "farm ready", ""))

    assert result.error_time is None
    assert result.error_code == 2104
    assert result.error_string == "farm ready"


def test_normalizes_timestamped_error_callback() -> None:
    result = normalize_ibkr_error_args((1_720_000_000_000, 2104, "farm ready", ""))

    assert result.error_time == 1_720_000_000_000
    assert result.error_code == 2104
    assert result.error_string == "farm ready"


@pytest.mark.parametrize("args", [(), (2104,), ("bad", "message"), ("bad", 2104, "message")])
def test_rejects_invalid_error_callback(args: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        normalize_ibkr_error_args(args)
