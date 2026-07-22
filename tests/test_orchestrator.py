from app.collectors.orchestrator import run_all_collectors


def _patch_all_collectors(mocker, **overrides):
    """Patches every collector run_all_collectors() calls to a no-op success
    (0 inserted) by default; overrides lets a specific test make one raise
    or return a real count, to verify the others still run regardless."""
    targets = {
        "app.collectors.reddit.store_reddit_trends": 0,
        "app.collectors.tiktok.store_tiktok_trends": 0,
        "app.collectors.youtube.fetch_youtube_trending": [],
        "app.collectors.youtube.store_youtube_trends": 0,
        "app.collectors.xiaohongshu.store_xhs_signals": 0,
        "app.collectors.twitter.store_twitter_trends": 0,
        "app.collectors.pinterest.store_pinterest_signals": 0,
        "app.collectors.wikipedia.store_wikipedia_trends": 0,
        "app.collectors.bluesky.store_bluesky_trends": 0,
        "app.collectors.instagram.store_instagram_trends": 0,
    }
    for target, default in targets.items():
        if target in overrides:
            value = overrides[target]
            if isinstance(value, Exception):
                mocker.patch(target, side_effect=value)
            else:
                mocker.patch(target, return_value=value)
        else:
            mocker.patch(target, return_value=default)


class TestRunAllCollectors:
    def test_one_collector_raising_does_not_block_the_others(self, mocker):
        _patch_all_collectors(
            mocker,
            **{
                "app.collectors.tiktok.store_tiktok_trends": Exception("tiktok is down"),
                "app.collectors.reddit.store_reddit_trends": 5,
                "app.collectors.instagram.store_instagram_trends": 3,
            },
        )

        results = run_all_collectors()

        assert results["tiktok"] == 0  # failed collector reports 0, doesn't raise out
        assert results["reddit"] == 5
        assert results["instagram"] == 3

    def test_every_collector_key_present_even_when_all_succeed_with_zero(self, mocker):
        _patch_all_collectors(mocker)

        results = run_all_collectors()

        for key in ("reddit", "tiktok", "youtube", "xhs", "twitter", "pinterest", "wikipedia", "bluesky", "instagram"):
            assert key in results

    def test_total_is_sum_of_all_individual_results(self, mocker):
        _patch_all_collectors(
            mocker,
            **{
                "app.collectors.reddit.store_reddit_trends": 2,
                "app.collectors.tiktok.store_tiktok_trends": 3,
                "app.collectors.instagram.store_instagram_trends": 4,
            },
        )

        results = run_all_collectors()

        assert results["total"] == sum(v for k, v in results.items() if k != "total")

    def test_all_collectors_failing_returns_zeros_not_a_crash(self, mocker):
        _patch_all_collectors(
            mocker,
            **{
                "app.collectors.reddit.store_reddit_trends": Exception("boom"),
                "app.collectors.tiktok.store_tiktok_trends": Exception("boom"),
                "app.collectors.youtube.fetch_youtube_trending": Exception("boom"),
                "app.collectors.xiaohongshu.store_xhs_signals": Exception("boom"),
                "app.collectors.twitter.store_twitter_trends": Exception("boom"),
                "app.collectors.pinterest.store_pinterest_signals": Exception("boom"),
                "app.collectors.wikipedia.store_wikipedia_trends": Exception("boom"),
                "app.collectors.bluesky.store_bluesky_trends": Exception("boom"),
                "app.collectors.instagram.store_instagram_trends": Exception("boom"),
            },
        )

        results = run_all_collectors()

        assert results["total"] == 0

    def test_youtube_probe_failure_skips_store_call_but_does_not_raise(self, mocker):
        _patch_all_collectors(mocker, **{"app.collectors.youtube.fetch_youtube_trending": []})
        mock_store = mocker.patch("app.collectors.youtube.store_youtube_trends")

        results = run_all_collectors()

        assert results["youtube"] == 0
        mock_store.assert_not_called()
