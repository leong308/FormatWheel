"""The same 73 actions and wheel positions as the macOS catalog."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = json.loads(Path(__file__).with_name("catalog_data.json").read_text(encoding="utf-8"))
ALIASES = {"jpeg": "jpg", "jpe": "jpg", "tif": "tiff", "heif": "heic", "htm": "html", "markdown": "md", "aif": "aiff", "aifc": "aiff", "oga": "opus", "ogg": "opus"}
EXTENSIONS = {
    "image": "png jpg jpeg jpe heic heif webp avif gif tiff tif bmp ico icns jpeg2000 jp2 jxl dng cr2 nef arw",
    "video": "mp4 m4v mov webm mkv flv avi wmv ts m2ts mts 3gp ogv mpeg mpg",
    "audio": "mp3 m4a aac wav flac aiff aif aifc opus ogg oga wma ape amr alac m4r caf",
    "document": "txt text md markdown rtf rtfd html htm doc docx odt wordml webarchive",
}


def canonical_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return ALIASES.get(ext, ext)


def file_kind(path: Path | str) -> str:
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    if path.is_dir():
        return "document" if ext == "rtfd" else "other"
    if ext == "pdf":
        return "pdf"
    return next((kind for kind, exts in EXTENSIONS.items() if ext in exts.split()), "other")


@dataclass
class WheelOption:
    id: str
    title: str = ""
    ammo: str = ""
    detail: str = ""
    big: str | None = None
    symbol: str | None = None
    enabled: bool = True
    note: str | None = None
    stats: list[float] | None = None


@dataclass
class WheelPage:
    name: str
    slots: list[WheelOption | None]


@dataclass
class WheelContext:
    files: list[Path]
    kind: str
    pages: list[WheelPage]
    headline: str
    summary: str
    stat_labels: list[str] = field(default_factory=list)
    base: list[float] = field(default_factory=list)

    @property
    def statLabels(self):
        return self.stat_labels


PAGE_IDS = {
    "image": [["img.to." + x for x in ("png", "jpg", "heic", "webp", "pdf", "avif", "gif", "tiff")],
              ["img." + x for x in ("compress", "half", "cutout", "ocr", "mono", "rotate", "strip", "backdrop")]],
    "pdf": [["pdf.to." + x for x in ("png", "jpg", "long", "docx", "txt", "md", "rtf", "html")],
            ["pdf.compress", "pdf.split", "pdf.merge", "pdf.rotate", "pdf.mono", "pdf.ocr", "pdf.strip", "gen.zip"]],
    "video": [["vid.to." + x for x in ("mp4", "mov", "hevc", "webm", "gif", "mp3", "m4a", "wav")],
              ["vid." + x for x in ("compress", "mute", "720p", "cover", "fast", "slow", "strip")] + ["gen.zip"]],
    "audio": [["aud.to." + x for x in ("mp3", "m4a", "wav", "flac", "aiff", "opus", "alac", "m4r")],
              ["aud.compress", "aud.mono", "aud.loud", "aud.fast", None, None, "gen.zip", "gen.path"]],
    "document": [["doc.to." + x for x in ("pdf", "docx", "txt", "md", "html", "rtf", "odt", "doc")],
                 ["doc.count", None, "doc.copy", None, "doc.strip", None, "gen.zip", "gen.path"]],
    "other": [["gen.zip", None, "gen.path", None, "gen.name", None, "gen.sha", None]],
}
LABELS = {"image": ["画质", "压缩率", "兼容性", "透明"], "pdf": ["版式还原", "可编辑", "体积小", "兼容性"], "video": ["画质", "压缩率", "兼容性"], "audio": ["音质", "压缩率", "兼容性"], "document": ["排版还原", "可编辑", "兼容性"]}
TITLES = {"image": "图片", "pdf": "PDF", "video": "视频", "audio": "音频", "document": "文档", "other": "文件"}


def all_ids() -> list[str]:
    return list(dict.fromkeys(action for pages in PAGE_IDS.values() for page in pages for action in page if action))


def context(files: list[Path | str]) -> WheelContext:
    paths = [Path(p).absolute() for p in files]
    kinds = [file_kind(p) for p in paths]
    kind = max(dict.fromkeys(kinds), key=kinds.count) if kinds else "other"
    same = [p for p in paths if file_kind(p) == kind]
    exts = {canonical_ext(p.suffix) for p in same}
    current = next(iter(exts)) if len(exts) == 1 else None
    traits = DATA["traits"].get({"document": "doc"}.get(kind, kind), {})
    base = traits.get("pdf" if kind == "pdf" else current, traits.get("other", []))
    pages = []
    for page_index, ids in enumerate(PAGE_IDS[kind]):
        slots = []
        for action in ids:
            if action is None:
                slots.append(None)
                continue
            option = WheelOption(**DATA["actions"][action])
            if action == "vid.compress":
                option.detail = "H.264 智能压缩，体积大幅缩小"
            if ".to." in action:
                target = action.split(".")[-1]
                option.stats = traits.get(target)
                unchanged = target == current or (target == "m4a" and current == "aac") or (target == "mp4" and current == "m4v")
                if unchanged and action not in ("img.to.pdf", "vid.to.hevc", "aud.to.alac"):
                    option.enabled, option.ammo, option.note = False, "当前", "已经是这个格式了"
            if action == "img.to.pdf" and len(same) > 1:
                option.title, option.ammo = "合并成 PDF", "合并"
                option.detail = f"{len(same)} 张图按顺序合成一个 PDF"
            if action == "pdf.merge":
                option.detail = f"把拖进来的 {len(same)} 个 PDF 按顺序合成一个"
                if len(same) < 2:
                    option.enabled, option.note = False, "同时拖 2 个以上 PDF 才能合并"
            if action == "doc.strip" and exts != {"docx"}:
                option.enabled, option.note = False, "只有 Word（.docx）文档会带作者信息"
            if action == "gen.sha" and any(p.is_dir() for p in paths):
                option.enabled, option.note = False, "文件夹算不了校验值"
            if option.enabled:
                from .engine import action_availability
                option.enabled, option.note = action_availability(action, same if not action.startswith("gen.") else paths)
                if not option.enabled:
                    option.ammo = "未装备"
            if option.stats is None and base:
                option.stats = list(base)
                adjustments = {"img.compress": {0: base[0] * .9, 1: base[1] + .35}, "img.half": {0: base[0] * .7, 1: base[1] + .3}, "img.cutout": {3: 1}, "pdf.compress": {0: base[0] * .92, 2: base[2] + .3}, "aud.compress": {0: base[0] * .8, 1: .95}, "vid.compress": {0: base[0] * .88, 1: base[1] + .3, 2: 1}, "vid.720p": {0: min(base[0], .6), 1: base[1] + .25}}
                for index, value in adjustments.get(action, {}).items():
                    option.stats[index] = min(1, max(0, value))
            slots.append(option)
        pages.append(WheelPage("通用" if kind == "other" else ("格式转换" if page_index == 0 else "工具"), slots))
    headline = paths[0].name if len(paths) == 1 else f"{len(paths)} 个文件"
    size = sum(p.stat().st_size for p in paths if p.exists() and p.is_file())
    summary = f"{size / 1024:,.1f} KB · {TITLES[kind]}"
    if len(paths) == 1:
        if kind == "image" and paths[0].is_file():
            try:
                from PIL import Image
                with Image.open(paths[0]) as image:
                    summary += f" · {image.width}×{image.height}"
            except (OSError, ValueError):
                pass
        summary += f" · {paths[0].suffix.lstrip('.').upper()}"
    if len(paths) > len(same):
        summary += f" · 另有 {len(paths) - len(same)} 个会跳过"
    return WheelContext(paths, kind, pages, headline, summary, LABELS.get(kind, []), list(base))


class Catalog:
    context = staticmethod(context)
    all_ids = staticmethod(all_ids)
