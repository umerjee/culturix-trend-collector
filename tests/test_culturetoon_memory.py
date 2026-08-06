"""Tests for app/services/culturetoon_memory.py — Qdrant/Voyage.ai are fully
mocked in every test here (mocking the QdrantClient class itself, not just
env vars) so this suite never makes a real network call or a real billed
Voyage embedding call, regardless of what QDRANT_URL/VOYAGE_API_KEY happen
to be set to in the environment running these tests."""
import os
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "zJZ2n2n0vXW5X8mYQKqVYV9YQe3F2Z8h0m3nQeF1nQ8=")

import uuid
from types import SimpleNamespace

import pytest

from app.services.culturetoon_memory import index_memory, delete_memory_index, retrieve_relevant_memories


def _fake_memory(**overrides):
    defaults = dict(
        id=uuid.uuid4(), character_variant_id=uuid.uuid4(), brand_id=uuid.uuid4(),
        memory_type="running_gag", content="Once tried to negotiate a Swiss train ticket.",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestIndexMemory:
    def test_no_qdrant_url_skips_silently(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=False)
        mocker.patch("os.getenv", side_effect=lambda k, d=None: None if k == "QDRANT_URL" else d)
        mock_embed = mocker.patch("app.embeddings.embed_text")

        index_memory(_fake_memory())
        mock_embed.assert_not_called()

    def test_embeds_and_upserts_with_correct_payload(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        mock_client = mock_client_cls.return_value
        mock_client.get_collections.return_value = SimpleNamespace(collections=[])
        mock_embed = mocker.patch("app.embeddings.embed_text", return_value=[0.1, 0.2, 0.3])

        memory = _fake_memory()
        index_memory(memory)

        mock_embed.assert_called_once_with(memory.content)
        mock_client.create_collection.assert_called_once()  # collection didn't exist
        mock_client.upsert.assert_called_once()
        _, kwargs = mock_client.upsert.call_args
        point = kwargs["points"][0]
        assert point.payload["character_variant_id"] == str(memory.character_variant_id)
        assert point.payload["content"] == memory.content

    def test_skips_create_collection_when_already_exists(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        mock_client = mock_client_cls.return_value
        mock_client.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="culturetoon_memories")]
        )
        mocker.patch("app.embeddings.embed_text", return_value=[0.1])

        index_memory(_fake_memory())
        mock_client.create_collection.assert_not_called()

    def test_qdrant_failure_does_not_raise(self, mocker):
        # Best-effort — the memory row is already durably saved in Postgres
        # by the time this is called, so a Qdrant outage must not surface
        # as an error to the caller.
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mocker.patch("qdrant_client.QdrantClient", side_effect=RuntimeError("connection refused"))

        index_memory(_fake_memory())  # must not raise


class TestDeleteMemoryIndex:
    def test_no_qdrant_url_skips_silently(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: None if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        delete_memory_index(uuid.uuid4())
        mock_client_cls.assert_not_called()

    def test_deletes_by_id(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        mock_client = mock_client_cls.return_value

        memory_id = uuid.uuid4()
        delete_memory_index(memory_id)

        mock_client.delete.assert_called_once_with(collection_name="culturetoon_memories", points_selector=[str(memory_id)])


class TestRetrieveRelevantMemories:
    def test_empty_variant_ids_returns_empty_without_any_calls(self, mocker):
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        result = retrieve_relevant_memories([], "some query")
        assert result == []
        mock_client_cls.assert_not_called()

    def test_empty_query_returns_empty_without_any_calls(self, mocker):
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        result = retrieve_relevant_memories([uuid.uuid4()], "   ")
        assert result == []
        mock_client_cls.assert_not_called()

    def test_no_qdrant_url_returns_empty(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: None if k == "QDRANT_URL" else d)
        result = retrieve_relevant_memories([uuid.uuid4()], "some query")
        assert result == []

    def test_collection_missing_returns_empty_without_embedding_call(self, mocker):
        # Cost-avoidance: if the collection doesn't exist yet, there's
        # nothing to search — must not spend a real Voyage embedding call
        # just to find that out.
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        mock_client_cls.return_value.get_collections.return_value = SimpleNamespace(collections=[])
        mock_embed = mocker.patch("app.embeddings.embed_text")

        result = retrieve_relevant_memories([uuid.uuid4()], "some query")
        assert result == []
        mock_embed.assert_not_called()

    def test_returns_content_from_search_results(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mock_client_cls = mocker.patch("qdrant_client.QdrantClient")
        mock_client = mock_client_cls.return_value
        mock_client.get_collections.return_value = SimpleNamespace(
            collections=[SimpleNamespace(name="culturetoon_memories")]
        )
        mock_client.search.return_value = [
            SimpleNamespace(payload={"content": "Once tried to negotiate a Swiss train ticket."}),
            SimpleNamespace(payload={"content": "Loves spicy food."}),
        ]
        mocker.patch("app.embeddings.embed_text", return_value=[0.1, 0.2])

        variant_id = uuid.uuid4()
        result = retrieve_relevant_memories([variant_id], "negotiating something")

        assert result == ["Once tried to negotiate a Swiss train ticket.", "Loves spicy food."]
        _, kwargs = mock_client.search.call_args
        assert kwargs["query_filter"].must[0].match.any == [str(variant_id)]

    def test_any_failure_returns_empty_not_raises(self, mocker):
        mocker.patch("os.getenv", side_effect=lambda k, d=None: "http://fake-qdrant" if k == "QDRANT_URL" else d)
        mocker.patch("qdrant_client.QdrantClient", side_effect=RuntimeError("connection refused"))

        result = retrieve_relevant_memories([uuid.uuid4()], "some query")
        assert result == []
