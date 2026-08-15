import subprocess


def git_sha() -> str | None:
    """HEAD sha, suffixed with -dirty when the working tree has uncommitted
    changes — a plain sha must mean the code actually matches that commit."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return f"{sha}-dirty" if dirty else sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None  # not a repo / git not installed
