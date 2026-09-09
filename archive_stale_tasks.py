#!/usr/bin/env python3
"""Archive tasks completed or >7 days overdue."""
import json, os
from datetime import datetime, timedelta
MEMORY = os.path.expanduser("~/ai-twin-memory")
TASKS = os.path.join(MEMORY, "tasks.json")
ARCHIVE = os.path.join(MEMORY, "tasks_archive.json")
def main():
    if not os.path.exists(TASKS): return
    with open(TASKS) as f: tasks = json.load(f)
    cutoff = datetime.now() - timedelta(days=7)
    keep, archive = [], []
    for t in tasks:
        if not t.get("completed"):
            due = t.get("due_date", "")
            if due and len(due) >= 10:
                try:
                    if datetime.fromisoformat(due[:10]) < cutoff:
                        archive.append(t); continue
                except: pass
            keep.append(t)
        else:
            comp = t.get("completed_at", "")
            if comp:
                try:
                    dt = datetime.fromisoformat(comp[:19] if "T" in comp else comp[:10])
                    if dt < cutoff: archive.append(t); continue
                except: pass
            keep.append(t)
    existing = []
    if os.path.exists(ARCHIVE):
        try:
            with open(ARCHIVE) as f: existing = json.load(f)
        except: pass
    existing.extend(archive)
    with open(TASKS, 'w') as f: json.dump(keep, f, indent=2)
    with open(ARCHIVE, 'w') as f: json.dump(existing, f, indent=2)
    print(f"Kept {len(keep)}. Archived {len(archive)}.")
if __name__ == "__main__": main()
