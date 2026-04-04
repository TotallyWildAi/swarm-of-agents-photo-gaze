"""In-memory similarity group service for managing photo similarity groups."""
from typing import Dict, List, Optional
import threading


class SimilarityGroupService:
    """Thread-safe in-memory store for similarity groups.

    Each group is a dict with keys: group_id, similarity_score, quality_score, members.
    Members are dicts with keys: photo_id, file_path, file_hash, filename.
    """

    def __init__(self):
        self._groups: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def add_group(self, group: dict) -> None:
        """Add or replace a similarity group. group must have 'group_id'."""
        gid = group["group_id"]
        with self._lock:
            self._groups[gid] = group

    def get_group(self, group_id: str) -> Optional[dict]:
        """Return a group by ID, or None if not found."""
        with self._lock:
            return self._groups.get(group_id)

    def get_all_groups(self) -> List[dict]:
        """Return a snapshot list of all groups."""
        with self._lock:
            return list(self._groups.values())

    def remove_group(self, group_id: str) -> bool:
        """Remove a group by ID. Returns True if it existed."""
        with self._lock:
            return self._groups.pop(group_id, None) is not None

    def clear(self) -> None:
        """Remove all groups."""
        with self._lock:
            self._groups.clear()
