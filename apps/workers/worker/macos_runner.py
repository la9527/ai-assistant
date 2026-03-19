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


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

REMINDERS_APPLESCRIPT = """
on run argv
    if (count of argv) < 1 then error "missing reminder name"
    set reminderName to item 1 of argv
    set reminderNote to ""
    set listName to "Reminders"
    if (count of argv) >= 2 then set reminderNote to item 2 of argv
    if (count of argv) >= 3 then set listName to item 3 of argv

    tell application "Reminders"
        if not running then launch
        if not (exists list listName) then
            make new list with properties {name:listName}
        end if
        tell list listName
            set newReminder to make new reminder with properties {name:reminderName, body:reminderNote}
            return listName & linefeed & name of newReminder
        end tell
    end tell
end run
""".strip()


class MacOSReminderRequest(BaseModel):
    name: str
    note: str = ""
    list_name: str = Field(default="Reminders", alias="list_name")
    message: str | None = None
    channel: str | None = None
    session_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None)


class MacOSReminderResponse(BaseModel):
    reply: str
    list_name: str = Field(alias="listName")
    name: str
    executed_at: str = Field(alias="executedAt")


@app.post("/macos/reminders", response_model=MacOSReminderResponse)
def create_reminder(payload: MacOSReminderRequest) -> MacOSReminderResponse:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    command = ["osascript"]
    for line in REMINDERS_APPLESCRIPT.splitlines():
        command.extend(["-e", line])
    command.extend([name, payload.note.strip(), payload.list_name.strip()])

    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="osascript command not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="AppleScript execution timed out.") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "unknown AppleScript failure"
        raise HTTPException(status_code=502, detail=detail) from exc

    lines = [l.strip() for l in completed.stdout.splitlines() if l.strip()]
    created_list = lines[0] if lines else payload.list_name
    created_name = lines[1] if len(lines) > 1 else name
    return MacOSReminderResponse(
        reply=f"미리알림의 {created_list} 목록에 '{created_name}'을(를) 추가했습니다.",
        listName=created_list,
        name=created_name,
        executedAt=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# System Events — 볼륨, 밝기, 다크모드 등
# ---------------------------------------------------------------------------

VOLUME_GET_APPLESCRIPT = 'output volume of (get volume settings)'
VOLUME_SET_APPLESCRIPT = 'set volume output volume {level}'
DARK_MODE_GET_APPLESCRIPT = 'tell application "System Events" to tell appearance preferences to return dark mode'
DARK_MODE_TOGGLE_APPLESCRIPT = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'


class SystemVolumeRequest(BaseModel):
    level: int = Field(ge=0, le=100)
    message: str | None = None
    channel: str | None = None
    session_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None)


class SystemInfoResponse(BaseModel):
    reply: str
    value: str
    executed_at: str = Field(alias="executedAt")


@app.get("/macos/system/volume", response_model=SystemInfoResponse)
def get_volume() -> SystemInfoResponse:
    try:
        completed = subprocess.run(
            ["osascript", "-e", VOLUME_GET_APPLESCRIPT],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    volume = completed.stdout.strip()
    return SystemInfoResponse(
        reply=f"현재 볼륨: {volume}%", value=volume,
        executedAt=datetime.now(UTC).isoformat(),
    )


@app.post("/macos/system/volume", response_model=SystemInfoResponse)
def set_volume(payload: SystemVolumeRequest) -> SystemInfoResponse:
    script = VOLUME_SET_APPLESCRIPT.format(level=payload.level)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SystemInfoResponse(
        reply=f"볼륨을 {payload.level}%로 설정했습니다.",
        value=str(payload.level),
        executedAt=datetime.now(UTC).isoformat(),
    )


@app.post("/macos/system/darkmode", response_model=SystemInfoResponse)
def toggle_dark_mode() -> SystemInfoResponse:
    try:
        subprocess.run(
            ["osascript", "-e", DARK_MODE_TOGGLE_APPLESCRIPT],
            check=True, capture_output=True, text=True, timeout=5,
        )
        completed = subprocess.run(
            ["osascript", "-e", DARK_MODE_GET_APPLESCRIPT],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    is_dark = completed.stdout.strip().lower() == "true"
    mode = "다크 모드" if is_dark else "라이트 모드"
    return SystemInfoResponse(
        reply=f"{mode}로 전환했습니다.", value=str(is_dark),
        executedAt=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# Finder — 열기 / 파일 목록 조회
# ---------------------------------------------------------------------------

FINDER_OPEN_APPLESCRIPT = """
on run argv
    if (count of argv) < 1 then error "missing folder path"
    set folderPath to item 1 of argv
    tell application "Finder"
        open POSIX file folderPath as alias
        activate
    end tell
    return folderPath
end run
""".strip()


class FinderOpenRequest(BaseModel):
    path: str
    message: str | None = None
    channel: str | None = None
    session_id: str | None = Field(default=None)
    user_id: str | None = Field(default=None)


@app.post("/macos/finder/open", response_model=SystemInfoResponse)
def finder_open(payload: FinderOpenRequest) -> SystemInfoResponse:
    folder_path = payload.path.strip()
    if not folder_path or ".." in folder_path:
        raise HTTPException(status_code=400, detail="invalid path")

    command = ["osascript"]
    for line in FINDER_OPEN_APPLESCRIPT.splitlines():
        command.extend(["-e", line])
    command.append(folder_path)

    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SystemInfoResponse(
        reply=f"Finder에서 '{folder_path}' 폴더를 열었습니다.",
        value=folder_path,
        executedAt=datetime.now(UTC).isoformat(),
    )


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8091)


if __name__ == "__main__":
    main()