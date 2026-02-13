from __future__ import annotations

import re
from typing import Iterator, Optional, Sequence

from bson.binary import Binary
from pymongo import MongoClient, UpdateOne

from langchain_core.stores import BaseStore


class MongoByteStore(BaseStore[str, bytes]):
    """Mongo-backed ByteStore for LangChain.

    Stores values as raw bytes in MongoDB. Keys are stored as `_id`.
    """

    def __init__(
        self,
        *,
        mongo_uri: str,
        db_name: str = "multimodal",
        collection_name: str = "rag_docstore",
        server_selection_timeout_ms: int = 2000,
        connect_timeout_ms: int = 2000,
        socket_timeout_ms: int = 2000,
    ) -> None:
        self._client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
            connectTimeoutMS=connect_timeout_ms,
            socketTimeoutMS=socket_timeout_ms,
        )
        self._collection = self._client[db_name][collection_name]

    def close(self) -> None:
        self._client.close()

    def mget(self, keys: Sequence[str]) -> list[Optional[bytes]]:
        if not keys:
            return []
        docs = self._collection.find({"_id": {"$in": list(keys)}}, {"v": 1})
        by_id: dict[str, bytes] = {}
        for doc in docs:
            val = doc.get("v")
            if isinstance(val, (bytes, bytearray)):
                by_id[str(doc["_id"])] = bytes(val)
            elif isinstance(val, Binary):
                by_id[str(doc["_id"])] = bytes(val)
        return [by_id.get(k) for k in keys]

    def mset(self, key_value_pairs: Sequence[tuple[str, bytes]]) -> None:
        if not key_value_pairs:
            return
        ops = []
        for key, value in key_value_pairs:
            if not isinstance(value, (bytes, bytearray)):
                raise TypeError(f"MongoByteStore expects bytes values; got {type(value)}")
            ops.append(
                UpdateOne(
                    {"_id": key},
                    {"$set": {"v": Binary(bytes(value))}},
                    upsert=True,
                )
            )
        self._collection.bulk_write(ops, ordered=False)

    def mdelete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        self._collection.delete_many({"_id": {"$in": list(keys)}})

    def yield_keys(self, *, prefix: Optional[str] = None) -> Iterator[str]:
        query = {}
        if prefix is not None:
            # Safe prefix match using escaped regex.
            query = {"_id": {"$regex": f"^{re.escape(prefix)}"}}
        for doc in self._collection.find(query, {"_id": 1}):
            yield str(doc["_id"])

