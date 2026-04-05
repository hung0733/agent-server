from __future__ import annotations

import asyncio
import re
from pathlib import Path


class FileOps:
    def __init__(self, workspace_root: str = "/workspace") -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            candidate = candidate.relative_to("/")
        resolved = (self.workspace_root / candidate).resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("path must stay within /workspace") from exc
        return resolved

    def _display(self, path: Path) -> str:
        return str(Path("/workspace") / path.relative_to(self.workspace_root))

    def _validate_glob(self, value: str) -> None:
        if value.startswith("/") or ".." in Path(value).parts:
            raise ValueError("glob must stay within /workspace")

    def _extract_patch_target_paths(self, patch: str) -> list[str]:
        targets: list[str] = []
        for line in patch.splitlines():
            if line.startswith(("--- ", "+++ ")):
                raw_path = line[4:].split("\t", 1)[0].strip()
                if raw_path and raw_path != "/dev/null":
                    targets.append(raw_path)
        return targets

    def _validate_patch_targets(self, patch: str, strip: int) -> None:
        for raw_path in self._extract_patch_target_paths(patch):
            path_obj = Path(raw_path)
            if path_obj.is_absolute():
                self._resolve(raw_path)
                continue
            parts = [part for part in path_obj.parts if part and part != path_obj.anchor]
            if strip > 0:
                parts = parts[strip:]
            normalized = "." if not parts else str(Path(*parts))
            self._resolve(normalized)

    async def read_file(self, path: str, encoding: str) -> dict:
        resolved = self._resolve(path)
        return {"content": resolved.read_text(encoding=encoding), "path": self._display(resolved)}

    async def write_file(self, path: str, content: str, encoding: str) -> dict:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return {"path": self._display(resolved)}

    async def edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool, encoding: str) -> dict:
        resolved = self._resolve(path)
        original = resolved.read_text(encoding=encoding)
        if old_string not in original:
            return {"path": self._display(resolved), "replacements": 0}
        if replace_all:
            updated = original.replace(old_string, new_string)
            count = original.count(old_string)
        else:
            updated = original.replace(old_string, new_string, 1)
            count = 1
        resolved.write_text(updated, encoding=encoding)
        return {"path": self._display(resolved), "replacements": count}

    async def apply_patch(self, patch: str, strip: int) -> dict:
        try:
            self._validate_patch_targets(patch, strip)
        except ValueError as exc:
            raise RuntimeError("patch target escapes sandbox workspace") from exc
        proc = await asyncio.create_subprocess_exec(
            "patch",
            f"-p{strip}",
            "--batch",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.workspace_root),
        )
        stdout, stderr = await proc.communicate(input=patch.encode())
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace") or stdout.decode(errors="replace"))
        return {"stdout": stdout.decode(errors="replace")}

    async def grep_files(self, pattern: str, path: str, recursive: bool, ignore_case: bool, include: str, max_results: int) -> dict:
        root = self._resolve(path)
        if include:
            self._validate_glob(include)
        flags = re.IGNORECASE if ignore_case else 0
        compiled = re.compile(pattern, flags)
        if root.is_file():
            search_files = [root]
        else:
            glob_pattern = f"**/{include}" if include and recursive else (include or "**/*" if recursive else include or "*")
            search_files = [item for item in root.glob(glob_pattern) if item.is_file()]
        matches: list[str] = []
        for file_path in search_files:
            text = file_path.read_text(errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    matches.append(f"{self._display(file_path)}:{lineno}:{line}")
                    if len(matches) >= max_results:
                        return {"matches": matches}
        return {"matches": matches}

    async def find_files(self, pattern: str, path: str, max_results: int) -> dict:
        root = self._resolve(path)
        self._validate_glob(pattern)
        return {"matches": [self._display(item) for item in sorted(root.glob(pattern))[:max_results]]}

    async def list_dir(self, path: str, show_hidden: bool) -> dict:
        root = self._resolve(path)
        entries = []
        for item in sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name)):
            if not show_hidden and item.name.startswith("."):
                continue
            entries.append({"name": item.name, "is_file": item.is_file(), "size": item.stat().st_size if item.is_file() else 0})
        return {"path": self._display(root), "entries": entries}
