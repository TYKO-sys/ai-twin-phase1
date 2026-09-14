"""
Idempotent migrations that run on every twin startup.

Each migration:
- Has a unique ID (string)
- Checks if it's already been applied
- Is safe to run multiple times
- Handles the case where the user skipped updates and jumped ahead

Tracked in ~/ai-twin-memory/applied_migrations.json
"""
import json
import os
import logging
from pathlib import Path

log = logging.getLogger("migrations")

MEMORY_DIR = Path.home() / "ai-twin-memory"
APPLIED_FILE = MEMORY_DIR / "applied_migrations.json"


def _load_applied() -> set:
    """Load the set of already-applied migration IDs."""
    try:
        if APPLIED_FILE.exists():
            data = json.loads(APPLIED_FILE.read_text())
            return set(data.get("applied", []))
    except Exception:
        pass
    return set()


def _mark_applied(migration_id: str):
    """Mark a migration as applied."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        applied = _load_applied()
        applied.add(migration_id)
        APPLIED_FILE.write_text(json.dumps({
            "applied": sorted(list(applied))
        }, indent=2))
    except Exception as e:
        log.warning(f"Could not mark migration {migration_id} as applied: {e}")


def _is_safety_leak(content: str) -> bool:
    """Detect if KB update content is safety-classifier output."""
    if not content:
        return False
    leak_patterns = [
        "user safety",
        "safety categories",
        "safety: safe",
        "safety: unsafe",
        "pii/privacy",
        "safety classification",
    ]
    content_lower = content.lower()[:200]
    return any(p in content_lower for p in leak_patterns)


# ============================================================
# MIGRATIONS — each is idempotent
# ============================================================

def migration_001_clean_identity_safety_leak():
    """Clean 'User Safety: unsafe' from identity.md if present."""
    identity_path = MEMORY_DIR / "knowledge" / "identity.md"
    if not identity_path.exists():
        return
    try:
        content = identity_path.read_text()
        if _is_safety_leak(content):
            # Replace with known-good facts
            identity_path.write_text(
                "You live in Baltimore.\n"
                "You are pursuing a WGU AI Engineering degree with an October 1 start.\n"
                "You use crutches for mobility and your orthopedic doctor is Dr. Lu.\n"
                "You are on probation with Agent Lewis as your PO and Mrs. Hamlet as your pre-trial case manager.\n"
                "You are in a treatment program directed by Tanika.\n"
            )
            log.info("Migration 001: cleaned identity.md safety leak")
    except Exception as e:
        log.warning(f"Migration 001 failed: {e}")


def migration_002_complete_stale_reschedule_task():
    """Complete the 'Reschedule orthopedic consult (Sept 14)' task if not already done."""
    tasks_path = MEMORY_DIR / "tasks.json"
    if not tasks_path.exists():
        return
    try:
        tasks = json.loads(tasks_path.read_text())
        changed = False
        for t in tasks:
            title = t.get("title", "").lower()
            if "reschedule" in title and "ortho" in title and not t.get("completed"):
                t["completed"] = True
                t["completed_at"] = "2026-09-09T12:00:00"
                t["status"] = "done"
                changed = True
                log.info(f"Migration 002: completed stale task '{t.get('title')}'")
        if changed:
            tasks_path.write_text(json.dumps(tasks, indent=2))
    except Exception as e:
        log.warning(f"Migration 002 failed: {e}")


def migration_003_clean_other_kb_safety_leaks():
    """Scan all KB files for safety-classifier output and clean if found."""
    kb_dir = MEMORY_DIR / "knowledge"
    if not kb_dir.exists():
        return
    try:
        for f in kb_dir.glob("*.md"):
            content = f.read_text()
            if _is_safety_leak(content):
                # Don't wipe — just remove the leaked lines
                lines = content.split('\n')
                cleaned = [l for l in lines if not _is_safety_leak(l)]
                f.write_text('\n'.join(cleaned).strip() + '\n')
                log.info(f"Migration 003: cleaned safety leak from {f.name}")
    except Exception as e:
        log.warning(f"Migration 003 failed: {e}")


def migration_004_clean_diagnostic_test_tasks():
    """Remove 'Diagnostic test task' entries created by diagnostic.py."""
    tasks_path = MEMORY_DIR / "tasks.json"
    if not tasks_path.exists():
        return
    try:
        tasks = json.loads(tasks_path.read_text())
        before = len(tasks)
        tasks = [t for t in tasks if t.get("title", "").lower().strip() != "diagnostic test task"]
        after = len(tasks)
        if before != after:
            tasks_path.write_text(json.dumps(tasks, indent=2))
            log.info(f"Migration 004: removed {before - after} diagnostic test tasks")
    except Exception as e:
        log.warning(f"Migration 004 failed: {e}")


def migration_005_archive_old_fired_reminders():
    """Archive fired reminders older than 7 days."""
    from datetime import datetime, timedelta
    reminders_path = MEMORY_DIR / "reminders.json"
    archive_path = MEMORY_DIR / "reminders_archive.json"
    if not reminders_path.exists():
        return
    try:
        reminders = json.loads(reminders_path.read_text())
        cutoff = datetime.now() - timedelta(days=7)
        keep, archive = [], []
        for r in reminders:
            if r.get("fired"):
                try:
                    dt = datetime.fromisoformat(r.get("when_iso", ""))
                    if dt < cutoff:
                        archive.append(r)
                        continue
                except:
                    pass
            keep.append(r)
        if archive:
            existing = []
            if archive_path.exists():
                try:
                    existing = json.loads(archive_path.read_text())
                except:
                    pass
            existing.extend(archive)
            reminders_path.write_text(json.dumps(keep, indent=2))
            archive_path.write_text(json.dumps(existing, indent=2))
            log.info(f"Migration 005: archived {len(archive)} old fired reminders")
    except Exception as e:
        log.warning(f"Migration 005 failed: {e}")


# Registry: (id, function) pairs in order
MIGRATIONS = [
    ("001_clean_identity_safety_leak", migration_001_clean_identity_safety_leak),
    ("002_complete_stale_reschedule_task", migration_002_complete_stale_reschedule_task),
    ("003_clean_other_kb_safety_leaks", migration_003_clean_other_kb_safety_leaks),
    ("004_clean_diagnostic_test_tasks", migration_004_clean_diagnostic_test_tasks),
    ("005_archive_old_fired_reminders", migration_005_archive_old_fired_reminders),
]


def run_pending_migrations():
    """Run all pending migrations. Called on every startup."""
    applied = _load_applied()
    for migration_id, func in MIGRATIONS:
        if migration_id not in applied:
            try:
                log.info(f"Running migration: {migration_id}")
                func()
                _mark_applied(migration_id)
            except Exception as e:
                log.error(f"Migration {migration_id} failed: {e}")
                # Mark as applied anyway so we don't block startup
                _mark_applied(migration_id)
