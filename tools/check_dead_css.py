# tools/check_dead_css.py — 找出 CSS 里没有任何引用的类选择器
#
# 用法: .venv/Scripts/python.exe tools/check_dead_css.py
# 退出码: 0 = 无死规则, 1 = 有命中（可挂到提交前检查里）
#
# 只认这几种落点，别的写法（比如把类名塞进变量再传出去）会误报成死规则，
# 所以命中后必须人工 grep 复核再删：
#   HTML  class="a b"
#   JS    class="a b"（模板串里的标记）、className = 'a' + (x ? ' b' : '')
#         classList.add/remove/toggle/contains('a')、setAttribute('class', ...)
#         querySelector(All)('.a')、'.a .b' 形式的选择器串

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "static" / "css"
SOURCES = [ROOT / "templates" / "index.html", *(ROOT / "static" / "js").glob("*.js")]

COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
# 规则前奏（`{` 之前）里的类名：点号后必须接字母，避开 `.46`、`.woff2`、`.css`
CLASS_IN_SELECTOR_RE = re.compile(r"\.([A-Za-z][A-Za-z0-9_-]*)")
RULE_HEAD_RE = re.compile(r"([^{}]+)\{[^{}]*\}")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
STR_RE = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"")

HTML_CLASS_RE = re.compile(r'class\s*=\s*"([^"]*)"')
JS_CLASS_ATTR_RE = re.compile(r'class="([^"]*)"')
JS_CLASSNAME_RE = re.compile(r"className\s*=[^;\n]+")
JS_CLASSLIST_RE = re.compile(r"classList\.(?:add|remove|toggle|contains)\(([^;\n]*)\)")
JS_SETATTR_RE = re.compile(r"setAttribute\(\s*['\"]class['\"]\s*,([^;\n]*)\)")
JS_SELECTOR_RE = re.compile(r"querySelector(?:All)?\(\s*([^;\n]*?)\s*\)")

# 类名由变量拼出来、上面那些式子扫不到的，登记在这里。
# toast 色调：`static/js/ui.js:12  el.className = 'toast ' + type`，
# type 由 22 处调用点传入字面量 'success' / 'warn' / 'error'。
# 新增 toast 类型时这里要补一条，否则会被误报成死规则（误报不致命，漏报才致命）。
DYNAMIC = {"success", "warn", "error"}


def _strings(chunk):
    out = []
    for groups in STR_RE.findall(chunk):
        out.extend(g for g in groups if g)
    return out


def css_class_occurrences():
    """返回 {类名: {"文件:行号", ...}}，只取选择器位置。"""
    found = {}
    for path in sorted(CSS_DIR.glob("*.css")):
        text = COMMENT_RE.sub(" ", path.read_text(encoding="utf-8"))
        for head_match in RULE_HEAD_RE.finditer(text):
            head = head_match.group(1)
            if head.lstrip().startswith("@"):
                continue
            spot = f"{path.name}:{text.count(chr(10), 0, head_match.start()) + 1}"
            for name in CLASS_IN_SELECTOR_RE.findall(head):
                found.setdefault(name, set()).add(spot)
    return found


def referenced_names():
    names = set()
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            chunks = HTML_CLASS_RE.findall(text)
        else:
            chunks = JS_CLASS_ATTR_RE.findall(text)
            for rx in (JS_CLASSNAME_RE, JS_CLASSLIST_RE, JS_SETATTR_RE, JS_SELECTOR_RE):
                for m in rx.finditer(text):
                    chunks.append(m.group(0))
        for chunk in chunks:
            names.update(WORD_RE.findall(chunk))
            for inner in _strings(chunk):
                names.update(WORD_RE.findall(inner))
    return names


def main():
    occurrences = css_class_occurrences()
    used = referenced_names() | DYNAMIC
    dead = {name: spots for name, spots in occurrences.items() if name not in used}

    print(f"CSS 类选择器 {len(occurrences)} 个（{len(list(CSS_DIR.glob('*.css')))} 份样式表）"
          f"，引用扫描 {len(SOURCES)} 个文件")
    if not dead:
        print("无死规则")
        return 0

    print(f"零命中 {len(dead)} 个（删之前逐个 grep 复核）:\n")
    for name in sorted(dead):
        print(f"  .{name:<26} {', '.join(sorted(occurrences[name]))}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
