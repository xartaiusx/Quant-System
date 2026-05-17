"""Account adapter skeleton."""

from __future__ import annotations

from trader.config import TraderConfig
from trader.data.snapshots import mock_account_snapshot, mock_positions
from trader.models import AccountSnapshot, PositionSnapshot


class AccountClient:
    """Read-only account facade for future broker integration."""

    def __init__(self, config: TraderConfig) -> None:
        self.config = config

    def snapshot(self) -> AccountSnapshot:
        return mock_account_snapshot(self.config.ibkr_account_id)

    def positions(self) -> list[PositionSnapshot]:
        return mock_positions()
