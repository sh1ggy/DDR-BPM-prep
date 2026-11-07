"""
Release console: the one way to prepare, release and roll back DDR MD chart
content. `make admin` serves it on localhost; `poetry run python -m admin`
is the same actions as a CLI, for scripts and agents.

State is read from git, the filesystem and the live manifests every time, so
the console can't disagree with what's actually there. The only thing it
keeps itself is log/admin/ (gitignored): activity.jsonl and one log per job.
"""
