from app.media.quota import plan_blocks_media, quota_exceeded, MONTHLY_QUOTA


class TestPlanBlocksMedia:
    def test_free_plan_is_blocked(self):
        assert plan_blocks_media("free") is True

    def test_pro_plan_is_not_blocked(self):
        assert plan_blocks_media("pro") is False

    def test_enterprise_plan_is_not_blocked(self):
        assert plan_blocks_media("enterprise") is False

    def test_none_defaults_to_free_and_is_blocked(self):
        assert plan_blocks_media(None) is True

    def test_empty_string_defaults_to_free_and_is_blocked(self):
        assert plan_blocks_media("") is True


class TestQuotaExceeded:
    def test_under_quota_is_not_exceeded(self):
        assert quota_exceeded(month_count=10, requested=2, quota=50) is False

    def test_exactly_at_quota_is_not_exceeded(self):
        assert quota_exceeded(month_count=48, requested=2, quota=50) is False

    def test_over_quota_is_exceeded(self):
        assert quota_exceeded(month_count=49, requested=2, quota=50) is True

    def test_zero_usage_zero_requested_never_exceeds(self):
        assert quota_exceeded(month_count=0, requested=0, quota=50) is False

    def test_default_quota_constant_used_when_not_specified(self):
        assert quota_exceeded(month_count=MONTHLY_QUOTA, requested=1) is True
        assert quota_exceeded(month_count=MONTHLY_QUOTA - 1, requested=1) is False
