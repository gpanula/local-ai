"""Context Store for Arc-Orc-Rev pipeline run artifacts.

Provides storage abstraction for run context snapshots, task messages, and run state.
Handles hot (plain JSON files) and cold (.tar.zst archives) paths transparently.
Implements RFC v7 §10.
"""

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
from typing import Any, Dict, Optional

import zstandard as zstd

from mcp_core.workspace import WORKSPACE_ROOT

# Base directory for all runs
RUNS_DIR = os.path.join(WORKSPACE_ROOT, "sysadmin", "data", "runs")


class ContextStore:
    """Manages run context snapshots with dual hot/cold storage."""

    def __init__(self, runs_dir: str = RUNS_DIR):
        """Store runs_dir and ensure it exists."""
        self.runs_dir = os.path.realpath(runs_dir)
        os.makedirs(self.runs_dir, exist_ok=True)

    @staticmethod
    def prompt_hash(prompt: str) -> str:
        """Return SHA-256 hex digest of a prompt string (UTF-8 encoded)."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def _run_dir(self, run_id: str) -> str:
        """Get absolute path to hot run directory."""
        return os.path.join(self.runs_dir, run_id)

    def _archive_path(self, run_id: str) -> str:
        """Get absolute path to cold run archive."""
        return os.path.join(self.runs_dir, f"{run_id}.tar.zst")

    def save_snapshot(self, run_id: str, task_id: str, snapshot: dict) -> str:
        """Write context_snapshot.json to the hot run directory.

        Args:
            run_id: UUID string for the run.
            task_id: Task ID string (e.g. "t-001").
            snapshot: Dict matching ContextSnapshot schema from §10.4.

        Returns:
            Relative path to the saved file from WORKSPACE_ROOT.
        """
        task_dir = os.path.join(self._run_dir(run_id), "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)
        file_path = os.path.join(task_dir, "context_snapshot.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        return os.path.relpath(file_path, WORKSPACE_ROOT)

    def save_task_message(self, run_id: str, task_id: str, task_message: dict) -> str:
        """Write task_message.json to the hot run directory.

        Args:
            run_id: UUID string for the run.
            task_id: Task ID string (e.g. "t-001").
            task_message: Dict matching TaskMessage schema from §3.6.

        Returns:
            Relative path to the saved file from WORKSPACE_ROOT.
        """
        task_dir = os.path.join(self._run_dir(run_id), "tasks", task_id)
        os.makedirs(task_dir, exist_ok=True)
        file_path = os.path.join(task_dir, "task_message.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(task_message, f, indent=2)
        return os.path.relpath(file_path, WORKSPACE_ROOT)

    def save_state(self, run_id: str, state: dict) -> str:
        """Write state.json to the hot run directory root.

        Args:
            run_id: UUID string for the run.
            state: Dict matching state.json schema from §6.1.

        Returns:
            Relative path to the saved file from WORKSPACE_ROOT.
        """
        run_dir = self._run_dir(run_id)
        os.makedirs(run_dir, exist_ok=True)
        file_path = os.path.join(run_dir, "state.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return os.path.relpath(file_path, WORKSPACE_ROOT)

    def save_message(self, run_id: str, message_name: str, message: dict) -> str:
        """Write an arbitrary phase message JSON (e.g., plan, annotated_plan).

        Args:
            run_id: UUID string for the run.
            message_name: Base name without extension (e.g. "plan", "annotated_plan").
            message: Dict message content.

        Returns:
            Relative path to the saved file from WORKSPACE_ROOT.
        """
        msg_dir = os.path.join(self._run_dir(run_id), "messages")
        os.makedirs(msg_dir, exist_ok=True)
        file_path = os.path.join(msg_dir, f"{message_name}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(message, f, indent=2)
        return os.path.relpath(file_path, WORKSPACE_ROOT)

    def _extract_run_id_from_ref(self, ref: str) -> Optional[str]:
        """Attempt to extract run_id from a file path reference."""
        parts = Path(ref).parts
        for i, part in enumerate(parts):
            if part == "runs" and i + 1 < len(parts):
                return parts[i + 1]
        if parts:
            first = parts[0]
            # If first part looks like a run directory
            if os.path.exists(os.path.join(self.runs_dir, f"{first}.tar.zst")) or os.path.isdir(os.path.join(self.runs_dir, first)):
                return first
        return None

    def load(self, ref: str) -> dict:
        """Load a JSON file — transparently handles hot (plain) and cold (.tar.zst) paths.

        Args:
            ref: Relative path like "runs/<run_id>/tasks/t-001/context_snapshot.json"
                 or absolute path.

        Returns:
            Parsed JSON dict.

        Raises:
            FileNotFoundError: If neither hot file nor cold archive member exists.
        """
        candidate_paths = []
        if os.path.isabs(ref):
            candidate_paths.append(ref)
        else:
            candidate_paths.append(os.path.join(WORKSPACE_ROOT, ref))
            candidate_paths.append(os.path.join(self.runs_dir, ref))
            candidate_paths.append(os.path.join(WORKSPACE_ROOT, "sysadmin", "data", ref))
            for prefix in ["sysadmin/data/runs/", "runs/"]:
                if ref.startswith(prefix):
                    candidate_paths.append(os.path.join(self.runs_dir, ref[len(prefix):]))

        for p in candidate_paths:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)

        # File does not exist as plain file. Try archive path.
        run_id = self._extract_run_id_from_ref(ref)
        if run_id:
            archive_path = self._archive_path(run_id)
            if os.path.isfile(archive_path):
                return self._load_from_archive(archive_path, ref)

        # Also search if any archive in runs_dir matches
        if not run_id:
            for item in os.listdir(self.runs_dir):
                if item.endswith(".tar.zst"):
                    archive_path = os.path.join(self.runs_dir, item)
                    try:
                        return self._load_from_archive(archive_path, ref)
                    except FileNotFoundError:
                        continue

        raise FileNotFoundError(f"Cannot find context file or archive for reference: {ref}")

    def _load_from_archive(self, archive: str, member: str) -> dict:
        """Extract and parse a single JSON member from a .tar.zst archive.

        Args:
            archive: Absolute path to .tar.zst file.
            member: Path or partial path of member to extract.

        Returns:
            Parsed JSON dict.
        """
        if not os.path.isfile(archive):
            raise FileNotFoundError(f"Archive not found: {archive}")

        dctx = zstd.ZstdDecompressor()
        with open(archive, "rb") as f:
            with dctx.stream_reader(f) as zreader:
                tar_bytes = zreader.read()

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
            tar_members = tf.getmembers()
            # Try to match member
            target_info = None

            # 1. Exact match on member name
            for m in tar_members:
                if m.name == member:
                    target_info = m
                    break

            # 2. Normalize by removing runs/ or matching suffix
            if not target_info:
                clean_ref = member.replace("\\", "/")
                # Strip leading "runs/" or "sysadmin/data/runs/"
                for prefix in ["sysadmin/data/runs/", "runs/"]:
                    if clean_ref.startswith(prefix):
                        clean_ref = clean_ref[len(prefix):]

                for m in tar_members:
                    m_norm = m.name.replace("\\", "/")
                    if m_norm == clean_ref or m_norm.endswith(clean_ref) or clean_ref.endswith(m_norm):
                        target_info = m
                        break

            if not target_info:
                # 3. Match basename if unique path segment
                subpath = member.replace("\\", "/").split("/")[-1]
                for m in tar_members:
                    if m.name.endswith(subpath):
                        target_info = m
                        break

            if not target_info:
                available = [m.name for m in tar_members]
                raise FileNotFoundError(
                    f"Member '{member}' not found in archive '{archive}'. Available: {available}"
                )

            extracted = tf.extractfile(target_info)
            if extracted is None:
                raise FileNotFoundError(f"Failed to extract member '{target_info.name}' from archive")
            return json.load(extracted)

    def seal_run(self, run_id: str) -> str:
        """Compress a completed run directory into a .tar.zst archive and delete the directory.

        Args:
            run_id: The run ID to seal.

        Returns:
            Path to the created archive.
        """
        run_dir = self._run_dir(run_id)
        if not os.path.isdir(run_dir):
            raise FileNotFoundError(f"Run directory does not exist: {run_dir}")

        archive_path = self._archive_path(run_id)
        cctx = zstd.ZstdCompressor(level=3)

        with open(archive_path, "wb") as f:
            with cctx.stream_writer(f, closefd=False) as zwriter:
                with tarfile.open(fileobj=zwriter, mode="w|") as tf:
                    for root, dirs, files in os.walk(run_dir):
                        dirs.sort()
                        for file in sorted(files):
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, self.runs_dir)
                            tf.add(full_path, arcname=arcname)

        # Delete hot run directory after compression
        shutil.rmtree(run_dir)
        return archive_path
