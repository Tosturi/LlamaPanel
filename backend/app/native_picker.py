"""Run Tk on the main thread of a short-lived process, never the API thread."""
import asyncio
import json
from pathlib import Path
import sys


async def pick_path(mode: str, initial: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).resolve()), mode, initial,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode:
            return {"available": False, "path": None}
        result = json.loads(stdout)
        if not isinstance(result, dict) or not isinstance(result.get("available"), bool):
            return {"available": False, "path": None}
        return result
    except (TimeoutError, ValueError):
        return {"available": False, "path": None}
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


def main():
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        mode, initial = sys.argv[1:3]
        directory = Path(initial).expanduser() if initial else Path.home()
        if not directory.is_dir():
            directory = directory.parent
        if not directory.is_dir():
            directory = Path.home()
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        options = dict(parent=root, initialdir=str(directory), title='LlamaPanel — Select folder' if mode == 'directory' else 'LlamaPanel — Select executable')
        path = (filedialog.askdirectory(mustexist=True, **options) if mode == 'directory'
                else filedialog.askopenfilename(**options))
        print(json.dumps({"available": True, "path": path or None}))
    except Exception:
        print(json.dumps({"available": False, "path": None}))
    finally:
        if root is not None:
            root.destroy()


if __name__ == '__main__':
    main()
