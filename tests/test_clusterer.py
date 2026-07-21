from app.pipeline.nodes.clusterer import _tag_cluster_regions, _tag_cluster_reference_image


class TestTagClusterRegions:
    def test_tags_cluster_with_regions_of_its_example_posts(self):
        signals = [
            {"translated_content": "india movie post", "region": "IN"},
            {"translated_content": "another india post", "region": "IN"},
            {"translated_content": "us post", "region": "US"},
        ]
        clusters = [{"example_posts": ["india movie post", "another india post"]}]

        _tag_cluster_regions(clusters, signals)

        assert clusters[0]["regions"] == ["IN"]

    def test_cluster_spanning_multiple_regions_gets_all_of_them(self):
        signals = [
            {"translated_content": "a", "region": "IN"},
            {"translated_content": "b", "region": "US"},
        ]
        clusters = [{"example_posts": ["a", "b"]}]

        _tag_cluster_regions(clusters, signals)

        assert clusters[0]["regions"] == ["IN", "US"]

    def test_cluster_with_no_resolvable_region_gets_empty_list(self):
        signals = [{"translated_content": "a reddit post", "region": None}]
        clusters = [{"example_posts": ["a reddit post"]}]

        _tag_cluster_regions(clusters, signals)

        assert clusters[0]["regions"] == []

    def test_example_post_not_found_in_signals_is_ignored(self):
        signals = [{"translated_content": "a", "region": "US"}]
        clusters = [{"example_posts": ["some text that was never a real signal"]}]

        _tag_cluster_regions(clusters, signals)

        assert clusters[0]["regions"] == []

    def test_missing_example_posts_key_gets_empty_regions_not_a_crash(self):
        clusters = [{"name": "no example_posts key at all"}]

        _tag_cluster_regions(clusters, [])

        assert clusters[0]["regions"] == []


class TestTagClusterReferenceImage:
    def test_tags_cluster_with_image_of_its_first_matching_example_post(self):
        signals = [
            {"translated_content": "trea turner post", "image_url": "https://i.ytimg.com/vi/abc/hqdefault.jpg"},
            {"translated_content": "another post", "image_url": None},
        ]
        clusters = [{"example_posts": ["trea turner post", "another post"]}]

        _tag_cluster_reference_image(clusters, signals)

        assert clusters[0]["reference_image_url"] == "https://i.ytimg.com/vi/abc/hqdefault.jpg"

    def test_picks_first_non_null_image_among_multiple_matches(self):
        signals = [
            {"translated_content": "a", "image_url": None},
            {"translated_content": "b", "image_url": "https://example.com/b.jpg"},
        ]
        clusters = [{"example_posts": ["a", "b"]}]

        _tag_cluster_reference_image(clusters, signals)

        assert clusters[0]["reference_image_url"] == "https://example.com/b.jpg"

    def test_cluster_with_no_resolvable_image_gets_none(self):
        signals = [{"translated_content": "a reddit post", "image_url": None}]
        clusters = [{"example_posts": ["a reddit post"]}]

        _tag_cluster_reference_image(clusters, signals)

        assert clusters[0]["reference_image_url"] is None

    def test_example_post_not_found_in_signals_gets_none(self):
        signals = [{"translated_content": "a", "image_url": "https://example.com/a.jpg"}]
        clusters = [{"example_posts": ["some text that was never a real signal"]}]

        _tag_cluster_reference_image(clusters, signals)

        assert clusters[0]["reference_image_url"] is None

    def test_missing_example_posts_key_gets_none_not_a_crash(self):
        clusters = [{"name": "no example_posts key at all"}]

        _tag_cluster_reference_image(clusters, [])

        assert clusters[0]["reference_image_url"] is None
