from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.trend import Trend
from app.models.cluster import Cluster
from app.clustering_service import _fingerprint, _jaccard, _compute_momentum, _ai_label_clusters_batch, run_clustering


def _trend(id):
    return SimpleNamespace(id=id)


class TestFingerprint:
    def test_same_membership_produces_same_fingerprint_regardless_of_order(self):
        a = _fingerprint([_trend(3), _trend(1), _trend(2)])
        b = _fingerprint([_trend(1), _trend(2), _trend(3)])
        assert a == b

    def test_different_membership_produces_different_fingerprint(self):
        a = _fingerprint([_trend(1), _trend(2)])
        b = _fingerprint([_trend(1), _trend(3)])
        assert a != b

    def test_empty_list_is_stable(self):
        assert _fingerprint([]) == _fingerprint([])


class TestJaccard:
    def test_identical_sets_are_maximally_similar(self):
        assert _jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets_are_zero(self):
        assert _jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        assert _jaccard({1, 2, 3}, {2, 3, 4}) == 2 / 4

    def test_both_empty_is_zero_not_a_crash(self):
        assert _jaccard(set(), set()) == 0.0


class TestComputeMomentum:
    def test_no_prior_clusters_returns_none(self):
        momentum, previous_size = _compute_momentum({1, 2, 3}, {}, {})
        assert momentum is None
        assert previous_size is None

    def test_low_overlap_with_prior_cluster_treated_as_new_topic(self):
        # Regression-shaped: only 1/5 overlap, below _MOMENTUM_MIN_OVERLAP (0.3)
        old_members = {10: {1, 99, 98, 97, 96}}
        existing_by_id = {10: SimpleNamespace(size=5)}
        momentum, previous_size = _compute_momentum({1, 2, 3, 4, 5}, old_members, existing_by_id)
        assert momentum is None
        assert previous_size is None

    def test_growth_beyond_threshold_is_up(self):
        old_members = {10: {1, 2, 3, 4}}
        existing_by_id = {10: SimpleNamespace(size=4)}
        # 8 new members overlapping all 4 old ones — growth well past 15%
        momentum, previous_size = _compute_momentum({1, 2, 3, 4, 5, 6, 7, 8}, old_members, existing_by_id)
        assert momentum == "up"
        assert previous_size == 4

    def test_shrinkage_beyond_threshold_is_down(self):
        old_members = {10: {1, 2, 3, 4, 5, 6, 7, 8}}
        existing_by_id = {10: SimpleNamespace(size=8)}
        momentum, previous_size = _compute_momentum({1, 2, 3}, old_members, existing_by_id)
        assert momentum == "down"
        assert previous_size == 8

    def test_small_change_within_threshold_is_neutral(self):
        old_members = {10: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}}
        existing_by_id = {10: SimpleNamespace(size=10)}
        # Exact same membership — 0% change, well within the 15% threshold
        momentum, previous_size = _compute_momentum(set(range(1, 11)), old_members, existing_by_id)
        assert momentum == "neutral"
        assert previous_size == 10

    def test_best_overlap_picked_among_multiple_candidates(self):
        old_members = {
            10: {1, 2},           # 2/6 overlap with new set
            20: {1, 2, 3, 4, 5},  # 5/5 overlap with new set — best match
        }
        existing_by_id = {10: SimpleNamespace(size=2), 20: SimpleNamespace(size=5)}
        momentum, previous_size = _compute_momentum({1, 2, 3, 4, 5}, old_members, existing_by_id)
        assert previous_size == 5  # confirms cluster 20 was picked, not 10

    def test_previous_size_zero_returns_none_momentum_but_reports_size(self):
        old_members = {10: {1, 2, 3, 4}}
        existing_by_id = {10: SimpleNamespace(size=0)}
        momentum, previous_size = _compute_momentum({1, 2, 3, 4}, old_members, existing_by_id)
        assert momentum is None
        assert previous_size == 0


class TestAiLabelClustersBatch:
    def test_empty_list_returns_empty_dict_without_calling_the_api(self, mocker):
        mock_create = mocker.patch("app.clustering_service._anthropic.messages.create")
        assert _ai_label_clusters_batch([]) == {}
        mock_create.assert_not_called()

    def test_empty_content_raises_diagnosable_error_not_json_decode_error(self, mocker):
        # Regression test: response.content[0].text == "" used to hit
        # json.loads("") -> "Expecting value: line 1 column 1 (char 0)",
        # which gave no hint this was an empty-response case rather than a
        # malformed-JSON case.
        mock_response = SimpleNamespace(content=[SimpleNamespace(text="")])
        mocker.patch("app.clustering_service._anthropic.messages.create", return_value=mock_response)
        post = SimpleNamespace(platform="tiktok", title="t", content="c")

        with pytest.raises(ValueError, match="empty content"):
            _ai_label_clusters_batch([(0, [post])])

    def test_empty_content_list_also_raises_diagnosable_error(self, mocker):
        mock_response = SimpleNamespace(content=[])
        mocker.patch("app.clustering_service._anthropic.messages.create", return_value=mock_response)
        post = SimpleNamespace(platform="tiktok", title="t", content="c")

        with pytest.raises(ValueError, match="empty content"):
            _ai_label_clusters_batch([(0, [post])])

    def test_single_call_labels_every_cluster(self, mocker):
        mock_response = SimpleNamespace(content=[SimpleNamespace(text=(
            '{"0": {"theme": "Theme A", "summary": "Summary A"}, '
            '"1": {"theme": "Theme B", "summary": "Summary B"}}'
        ))])
        mock_create = mocker.patch("app.clustering_service._anthropic.messages.create", return_value=mock_response)
        post = SimpleNamespace(platform="tiktok", title="t", content="c")

        result = _ai_label_clusters_batch([(0, [post]), (1, [post])])

        mock_create.assert_called_once()  # one call, not one per cluster
        assert result[0]["theme"] == "Theme A"
        assert result[1]["theme"] == "Theme B"

    def test_cluster_missing_from_response_is_simply_absent_not_a_crash(self, mocker):
        # Model only returned label "0" -- label "1" should just be missing
        # from the result dict, letting the caller treat it as failed
        # without the whole batch raising.
        mock_response = SimpleNamespace(content=[SimpleNamespace(text=(
            '{"0": {"theme": "Theme A", "summary": "Summary A"}}'
        ))])
        mocker.patch("app.clustering_service._anthropic.messages.create", return_value=mock_response)
        post = SimpleNamespace(platform="tiktok", title="t", content="c")

        result = _ai_label_clusters_batch([(0, [post]), (1, [post])])

        assert 0 in result
        assert 1 not in result


@pytest.fixture
def clustering_db(mocker):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Trend.__table__, Cluster.__table__])
    TestSessionLocal = sessionmaker(bind=engine)
    mocker.patch("app.clustering_service.SessionLocal", TestSessionLocal)
    return TestSessionLocal


def _real_trend(session, **overrides):
    defaults = dict(platform="tiktok", content="c", embedding=[1.0, 0.0])
    defaults.update(overrides)
    t = Trend(**defaults)
    session.add(t)
    return t


def _stub_advisory_lock(mocker):
    # Postgres-only advisory lock functions don't exist in SQLite — stub
    # session.execute to report "lock acquired" without hitting the DB for
    # that specific call, real queries pass through.
    from sqlalchemy.orm import Session as _Session
    orig_execute = _Session.execute
    def fake_execute(self, stmt, *a, **kw):
        if "advisory_lock" in str(stmt):
            return SimpleNamespace(scalar=lambda: True)
        return orig_execute(self, stmt, *a, **kw)
    mocker.patch.object(_Session, "execute", fake_execute)


class TestRunClusteringPartialFailure:
    def test_one_clusters_ai_labeling_failure_does_not_roll_back_others(self, mocker, clustering_db):
        session = clustering_db()
        for i in range(6):
            _real_trend(session, embedding=[float(i), 0.0])
        session.commit()
        session.close()

        # Two labels -> two clusters of 3 trends each. HDBSCAN itself is
        # mocked; only run_clustering's own persistence logic is under test.
        mocker.patch("app.clustering_service.cluster_embeddings_hdbscan", return_value=[0, 0, 0, 1, 1, 1])
        _stub_advisory_lock(mocker)

        # The batched call succeeds overall but only returns a label for
        # cluster 1 -- cluster 0 is simply missing from the response, same
        # as a real malformed/incomplete model reply.
        mocker.patch(
            "app.clustering_service._ai_label_clusters_batch",
            return_value={1: {"theme": "Real theme", "summary": "Real summary"}},
        )

        result = run_clustering(limit=10, min_cluster_size=2)

        assert result["clusters_created"] == 1
        assert result["clusters_failed"] == 1

        session = clustering_db()
        try:
            # The one cluster that succeeded is actually persisted —
            # this is the behavior that used to be lost entirely when any
            # single cluster in the batch failed.
            assert session.query(Cluster).count() == 1
            assert session.query(Cluster).first().theme == "Real theme"
        finally:
            session.close()


class TestRunClusteringTotalLabelingFailurePreservesExisting:
    def test_total_failure_does_not_wipe_existing_clusters(self, mocker, clustering_db):
        # Regression test for the exact incident that lost all historic
        # clusters live: an Anthropic billing lapse meant EVERY candidate
        # cluster failed labeling in one run, which used to delete every
        # existing Cluster row as "stale" since none of them got
        # reused/recreated. Seed one existing cluster, then run a batch
        # where every trend forms new (non-matching-fingerprint) groups and
        # the whole batch labeling call fails.
        session = clustering_db()
        existing = Cluster(label=0, theme="Old theme", summary="Old summary", size=3, fingerprint="old-fp")
        session.add(existing)
        for i in range(6):
            _real_trend(session, embedding=[float(i), 0.0])
        session.commit()
        session.close()

        mocker.patch("app.clustering_service.cluster_embeddings_hdbscan", return_value=[0, 0, 0, 1, 1, 1])
        _stub_advisory_lock(mocker)
        mocker.patch("app.clustering_service._ai_label_clusters_batch", side_effect=RuntimeError("provider down"))

        result = run_clustering(limit=10, min_cluster_size=2)

        assert result["clusters_created"] == 0
        assert result["clusters_removed"] == 0
        assert "warning" in result

        session = clustering_db()
        try:
            # The pre-existing cluster must still be there, untouched.
            assert session.query(Cluster).count() == 1
            assert session.query(Cluster).first().theme == "Old theme"
        finally:
            session.close()


class TestRunClusteringLockContention:
    def test_skips_immediately_when_advisory_lock_not_acquired(self, mocker):
        mock_session = mocker.MagicMock()
        mock_session.execute.return_value.scalar.return_value = False  # pg_try_advisory_lock failed
        mocker.patch("app.clustering_service.SessionLocal", return_value=mock_session)

        result = run_clustering()

        assert result["skipped"] == "another run_clustering() call is already in progress"
        # Never got far enough to query trends when the lock wasn't acquired
        mock_session.query.assert_not_called()

    def test_releases_lock_on_success_path_exit(self, mocker):
        mock_session = mocker.MagicMock()
        # First execute() call = lock acquisition (succeeds); trends query
        # returns too few rows to cluster, short-circuiting before the second
        # advisory-lock-related execute() call at unlock time.
        mock_session.execute.return_value.scalar.return_value = True
        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mocker.patch("app.clustering_service.SessionLocal", return_value=mock_session)

        result = run_clustering(min_cluster_size=5)

        assert result["total_trends"] == 0
        assert "warning" in result
        # pg_advisory_unlock must still be called in the finally block
        unlock_calls = [
            c for c in mock_session.execute.call_args_list
            if "pg_advisory_unlock" in str(c.args[0])
        ]
        assert len(unlock_calls) == 1
