from datetime import UTC
from datetime import datetime
import subprocess

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field
import uvicorn


NOTES_APPLESCRIPT = """
on run argv
    if (count of argv) < 2 then error "missing title or body"
    set noteTitle to item 1 of argv
    set noteBody to item 2 of argv
    set folderName to "AI Assistant"
    if (count of argv) >= 3 then
        set folderName to item 3 of argv
    end if

    tell application "Notes"
        if not running then launch
        set targetAccount to first account
        if not (exists folder folderName of targetAccount) then
            make new folder at targetAccount with properties {name:folderName}
        end if
        set targetFolder to folder folderName of targetAccount
        set newNote to make new note at targetFolder with properties {name:noteTitle, body:noteBody}
        return folderName & linefeed & name of newNote
    end tell
end run
""".strip()


class MacOSNoteRequest(BaseModel):
    title: str
    body: str
    folder: str = "AI Assistant"
    message: str | None = None
    channel: str | None = None
    session_id: str | None = Field(default=None, alias="session_id")
    user_id: str | None = Field(default=None, alias="user_id")


class MacOSNoteResponse(BaseModel):
    reply: str
    folder: str
    title: str
    executed_at: str = Field(alias="executedAt")


app = FastAPI(title="AI Assistant macOS Runner", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/macos/notes", response_model=MacOSNoteResponse)
def create_note(payload: MacOSNoteRequest) -> MacOSNoteResponse:
    title = payload.title.strip()
    body = payload.body.strip()
    folder = payload.folder.strip() or "AI Assistant"

    if not title or not body:
        raise HTTPException(status_code=400, detail="title and body are required")

    command = ["osascript"]
    for line in NOTES_APPLESCRIPT.splitlines():
        command.extend(["-e", line])
    command.extend([title, body, folder])

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="osascript command not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="AppleScript execution timed out. Check macOS automation permissions for Notes.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "unknown AppleScript failure"
        raise HTTPException(status_code=502, detail=detail) from exc

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    created_folder = lines[0] if lines else folder
    created_title = lines[1] if len(lines) > 1 else title
    return MacOSNoteResponse(
        reply=f"Notes 앱의 {created_folder} 폴더에 '{created_title}' 메모를 생성했습니다.",
        folder=created_folder,
        title=created_title,
        executedAt=datetime.now(UTC).isoformat(),
    )


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8091)


if __name__ == "__main__":
    main()