"""Serve the built React application and public reading assets."""

from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
WEB_DIST = WEB_ROOT / "dist"


def page() -> FileResponse:
    target = WEB_DIST / "index.html"
    if not target.is_file():
        raise HTTPException(
            status_code=503, detail="请先执行 cd web && npm ci && npm run build"
        )
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


def asset(path: str) -> FileResponse:
    target = (WEB_DIST / "assets" / path).resolve()
    try:
        target.relative_to((WEB_DIST / "assets").resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="asset not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(
        target, headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )


def available_files(root: str | None) -> list[str]:
    if not root:
        return []
    return [
        name
        for name in ("transcript.txt", "article.md", "notes.md", "mindmap.md")
        if (Path(root) / name).is_file()
    ]


def episode_metadata(episode: dict) -> dict:
    return {
        "id": episode["id"],
        "eid": episode["eid"],
        "episode_url": episode["episode_url"],
        "title": episode["title"],
        "description": episode.get("description") or "",
        "published_at": episode["published_at"],
        "duration": episode["duration"],
        "status": episode["status"],
        "has_result": episode["status"] == "done" and bool(episode.get("result_dir")),
        "available_files": available_files(episode.get("result_dir"))
        if episode["status"] == "done"
        else [],
    }
