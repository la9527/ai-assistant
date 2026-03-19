"""macOS 자동화 MCP 서버.

AppleScript를 통해 Notes, Reminders, 시스템 볼륨, 다크모드, Finder를 제어한다.
기존 macos_runner.py(REST)와 동일한 기능을 MCP 프로토콜로 노출한다.

실행: python server.py (stdio 모드로 동작)
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ---------------------------------------------------------------------------
# AppleScript 정의
# ---------------------------------------------------------------------------

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

VOLUME_GET_APPLESCRIPT = "output volume of (get volume settings)"
VOLUME_SET_APPLESCRIPT = "set volume output volume {level}"
DARK_MODE_GET_APPLESCRIPT = 'tell application "System Events" to tell appearance preferences to return dark mode'
DARK_MODE_TOGGLE_APPLESCRIPT = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'

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

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _run_applescript(script: str, args: list[str] | None = None, timeout: int = 15) -> str:
    """AppleScript를 실행하고 stdout을 반환한다."""
    command = ["osascript"]
    if "\n" in script:
        for line in script.splitlines():
            command.extend(["-e", line])
    else:
        command.extend(["-e", script])
    if args:
        command.extend(args)

    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout.strip()


# ---------------------------------------------------------------------------
# MCP 서버 정의
# ---------------------------------------------------------------------------

server = Server("macos-automation")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="macos_note_create",
            description="macOS Notes 앱에 메모를 생성한다",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "메모 제목"},
                    "body": {"type": "string", "description": "메모 본문"},
                    "folder": {"type": "string", "description": "메모 폴더명 (기본: AI Assistant)"},
                },
                "required": ["title", "body"],
            },
        ),
        Tool(
            name="macos_reminder_create",
            description="macOS 미리알림에 항목을 추가한다",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "미리알림 이름"},
                    "note": {"type": "string", "description": "메모"},
                    "list_name": {"type": "string", "description": "미리알림 목록 이름 (기본: Reminders)"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="macos_volume_get",
            description="현재 macOS 시스템 볼륨을 조회한다",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="macos_volume_set",
            description="macOS 시스템 볼륨을 설정한다 (0-100)",
            inputSchema={
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "minimum": 0, "maximum": 100, "description": "볼륨 레벨 (0-100)"},
                },
                "required": ["level"],
            },
        ),
        Tool(
            name="macos_darkmode_toggle",
            description="macOS 다크모드를 전환한다",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="macos_finder_open",
            description="Finder에서 지정 폴더를 연다",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "열 폴더 경로"},
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "macos_note_create":
            return _handle_note_create(arguments)
        elif name == "macos_reminder_create":
            return _handle_reminder_create(arguments)
        elif name == "macos_volume_get":
            return _handle_volume_get()
        elif name == "macos_volume_set":
            return _handle_volume_set(arguments)
        elif name == "macos_darkmode_toggle":
            return _handle_darkmode_toggle()
        elif name == "macos_finder_open":
            return _handle_finder_open(arguments)
        else:
            return [TextContent(type="text", text=f"알 수 없는 도구: {name}")]
    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text="AppleScript 실행 시간이 초과되었습니다.")]
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "AppleScript 실행 실패"
        return [TextContent(type="text", text=f"AppleScript 오류: {detail}")]
    except FileNotFoundError:
        return [TextContent(type="text", text="osascript 명령을 찾을 수 없습니다. macOS에서만 실행 가능합니다.")]


def _handle_note_create(args: dict) -> list[TextContent]:
    title = args.get("title", "").strip()
    body = args.get("body", "").strip()
    folder = args.get("folder", "AI Assistant").strip()
    if not title or not body:
        return [TextContent(type="text", text="title과 body는 필수입니다.")]

    output = _run_applescript(NOTES_APPLESCRIPT, [title, body, folder])
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    created_folder = lines[0] if lines else folder
    created_title = lines[1] if len(lines) > 1 else title
    return [TextContent(
        type="text",
        text=f"Notes 앱의 {created_folder} 폴더에 '{created_title}' 메모를 생성했습니다.",
    )]


def _handle_reminder_create(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip()
    note = args.get("note", "").strip()
    list_name = args.get("list_name", "Reminders").strip()
    if not name:
        return [TextContent(type="text", text="name은 필수입니다.")]

    output = _run_applescript(REMINDERS_APPLESCRIPT, [name, note, list_name])
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    created_list = lines[0] if lines else list_name
    created_name = lines[1] if len(lines) > 1 else name
    return [TextContent(
        type="text",
        text=f"미리알림의 {created_list} 목록에 '{created_name}'을(를) 추가했습니다.",
    )]


def _handle_volume_get() -> list[TextContent]:
    volume = _run_applescript(VOLUME_GET_APPLESCRIPT, timeout=5)
    return [TextContent(type="text", text=f"현재 볼륨: {volume}%")]


def _handle_volume_set(args: dict) -> list[TextContent]:
    level = args.get("level")
    if level is None or not (0 <= int(level) <= 100):
        return [TextContent(type="text", text="level은 0-100 사이 정수여야 합니다.")]
    script = VOLUME_SET_APPLESCRIPT.format(level=int(level))
    _run_applescript(script, timeout=5)
    return [TextContent(type="text", text=f"볼륨을 {level}%로 설정했습니다.")]


def _handle_darkmode_toggle() -> list[TextContent]:
    _run_applescript(DARK_MODE_TOGGLE_APPLESCRIPT, timeout=5)
    result = _run_applescript(DARK_MODE_GET_APPLESCRIPT, timeout=5)
    is_dark = result.lower() == "true"
    mode = "다크 모드" if is_dark else "라이트 모드"
    return [TextContent(type="text", text=f"{mode}로 전환했습니다.")]


def _handle_finder_open(args: dict) -> list[TextContent]:
    path = args.get("path", "").strip()
    if not path or ".." in path:
        return [TextContent(type="text", text="유효한 경로가 필요합니다.")]
    _run_applescript(FINDER_OPEN_APPLESCRIPT, [path], timeout=10)
    return [TextContent(type="text", text=f"Finder에서 '{path}' 폴더를 열었습니다.")]


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

async def main() -> None:
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
