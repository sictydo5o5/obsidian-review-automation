#!/usr/bin/env python3
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class ReviewTask:
    line: str
    note: Optional[str]
    due_date: str  # ISO format YYYY-MM-DD


def load_env(path: Path) -> Dict[str, str]:
    """
    Minimal .env loader (no python-dotenv).
    Supports simple KEY=VALUE lines, ignores comments and blanks.
    """
    env: Dict[str, str] = {}
    if not path.exists():
        return env

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        # Remove optional surrounding quotes
        value = value.strip().strip('"').strip("'")
        env[key] = value
    return env


def get_env() -> Dict[str, str]:
    # Load from .env and overlay onto current os.environ (env vars win)
    file_env = load_env(ENV_PATH)
    merged = dict(file_env)
    merged.update(os.environ)
    return merged


TASK_PATTERN = re.compile(
    r"^- \[ \]\s*(?P<body>.+?)\s*📅\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$"
)


def parse_tasks_from_file(review_file: Path) -> List[ReviewTask]:
    if not review_file.exists():
        raise FileNotFoundError(f"Review file not found: {review_file}")

    tasks: List[ReviewTask] = []
    for raw in review_file.read_text(encoding="utf-8").splitlines():
        m = TASK_PATTERN.match(raw)
        if not m:
            continue
        body = m.group("body").strip()
        due = m.group("date")

        # Extract note name heuristically: remove leading "復習"などと番号、残りをノート名として扱う
        # 例: "復習① ノート名" -> "ノート名"
        note = None
        # Remove leading "復習" (any suffix) and following whitespace
        tmp = re.sub(r"^復習\S*\s*", "", body)
        note = tmp if tmp else None

        tasks.append(ReviewTask(line=raw, note=note, due_date=due))
    return tasks


def classify_tasks(tasks: List[ReviewTask]) -> Dict[str, List[Dict]]:
    # Use local date based on Asia/Tokyo
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).date()
    tomorrow = today + timedelta(days=1)

    today_str = today.isoformat()
    tomorrow_str = tomorrow.isoformat()

    result = {"today": [], "tomorrow": [], "others": []}

    for t in tasks:
        if t.due_date == today_str:
            result["today"].append(asdict(t))
        elif t.due_date == tomorrow_str:
            result["tomorrow"].append(asdict(t))
        else:
            result["others"].append(asdict(t))

    return {
        "today": result["today"],
        "tomorrow": result["tomorrow"],
        "meta": {
            "generated_at": datetime.now(JST).isoformat(),
            "today": today_str,
            "tomorrow": tomorrow_str,
        },
    }


def ensure_gist(
    token: str, gist_id: Optional[str], content: str
) -> str:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    payload = {
        "description": "Obsidian review tasks (auto-generated)",
        "public": False,
        "files": {
            "review_tasks.json": {
                "content": content,
            }
        },
    }

    if gist_id:
        # Update existing gist
        resp = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("id", gist_id)
    else:
        # Create new gist
        resp = requests.post(
            "https://api.github.com/gists",
            headers=headers,
            data=json.dumps(payload),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"]


def main() -> None:
    env = get_env()

    github_token = env.get("GITHUB_GIST_TOKEN")
    if not github_token:
        raise SystemExit("GITHUB_GIST_TOKEN is not set in .env or environment")

    gist_id = env.get("REVIEW_GIST_ID") or None

    vault_path = env.get("VAULT_PATH", "/Users/toyoda/Obsidian/MainVault")
    review_file_rel = env.get(
        "REVIEW_FILE_PATH", "03_知識/復習管理_20251001開始.md"
    )

    review_file = Path(vault_path) / review_file_rel

    tasks = parse_tasks_from_file(review_file)
    classified = classify_tasks(tasks)
    json_content = json.dumps(classified, ensure_ascii=False, indent=2)

    new_gist_id = ensure_gist(github_token, gist_id, json_content)

    # If REVIEW_GIST_ID was empty, print the new ID so user can copy to .env
    print(f"Gist ID: {new_gist_id}")


if __name__ == "__main__":
    main()


