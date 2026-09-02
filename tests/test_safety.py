from mail_organizer.config import Settings


def test_automatic_permanent_deletion_is_hard_disabled() -> None:
    assert Settings(dry_run=False).destructive_actions_allowed is False
