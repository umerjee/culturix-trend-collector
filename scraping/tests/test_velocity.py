from datetime import datetime, timedelta, timezone

from culturix_scraping.velocity import hours_since, is_high_velocity, velocity_score


class TestHoursSince:
    def test_naive_datetime_is_treated_as_utc(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        naive = datetime(2026, 1, 1)  # no tzinfo
        assert hours_since(naive, now=now) == 24.0

    def test_never_negative_for_a_future_timestamp(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        future = now + timedelta(hours=5)
        assert hours_since(future, now=now) == 0.0


class TestVelocityScore:
    def test_brand_new_post_scores_close_to_raw_likes(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert velocity_score(1000, now, now=now) == 1000.0  # 1000 / (0 + 1)

    def test_older_post_with_same_likes_scores_lower(self):
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        created = now - timedelta(hours=9)
        assert velocity_score(1000, created, now=now) == 100.0  # 1000 / (9 + 1)

    def test_zero_likes_scores_zero(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert velocity_score(0, now, now=now) == 0.0


class TestIsHighVelocity:
    def test_at_threshold_counts_as_high(self):
        assert is_high_velocity(500.0, threshold=500.0) is True

    def test_below_threshold_is_not_high(self):
        assert is_high_velocity(499.9, threshold=500.0) is False
