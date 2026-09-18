#!/usr/bin/env python3
"""docs/ 의 마크다운을 위키 스타일 정적 사이트로 변환한다.

의존성 없음 — 표준 라이브러리만 쓴다. 보드에서도, CI 에서도 같이 돌게 하려는 것이다.

    python3 tools/build_wiki.py            # site/ 에 생성
    python3 tools/build_wiki.py --out dist # 출력 위치 지정
    python3 tools/build_wiki.py --serve    # 생성하고 미리보기 서버 띄우기

구조:
    README.md          → site/index.html   (대문. 단계 구성의 원본이기도 하다)
    docs/<장>/<쪽>.md  → site/<장>/<쪽>.html
    tools/wiki.css     → site/style.css

다루는 마크다운 범위는 이 저장소가 실제로 쓰는 것에 맞췄다 —
제목 · 문단 · 코드펜스(목록 안에 들여쓴 것 포함) · 표(들여쓴 것 포함) ·
인용 · 중첩 목록 · 볼드 · 인라인 코드 · 링크 · 수평선.
일반 마크다운 파서가 아니므로 범위를 넘는 문법은 그대로 지나간다.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CSS_SRC = Path(__file__).resolve().parent / "wiki.css"

SITE_NAME = "IP카메라 기술 노트"
REPO_URL = "https://github.com/squid55/ipcam-notes"
BLOG_URL = "https://squid55.github.io/"   # 본 블로그. 이 위키는 그 아래 딸린 노트다.


# ════════════════════════════════════════════════════════════════════
#  인라인 변환
# ════════════════════════════════════════════════════════════════════

_CODE_SLOT = "\x00CODE{}\x00"


def rewrite_href(url: str) -> str:
    """문서 간 링크의 .md 를 .html 로 바꾼다. 앵커와 절대 URL 은 건드리지 않는다."""
    if url.startswith(("http://", "https://", "#", "mailto:")):
        return url
    if "#" in url:
        path, _, frag = url.partition("#")
        return f"{rewrite_href(path)}#{frag}" if path else url
    if url.endswith(".md"):
        return url[:-3] + ".html"
    return url


def inline(text: str, mark_measured: bool = True) -> str:
    """인라인 마크다운을 HTML 로. 코드 스팬을 먼저 떼어내 볼드·링크 변환에서 보호한다.

    mark_measured=True 면 문장 안의 `실측:` 을 작은 표식으로 감싼다.
    목록 항목 안의 실측은 상자로 승격되지 않으므로 이 표식이 유일한 단서가 된다.
    상자로 이미 승격된 문단에서는 False 를 줘서 표식이 겹치지 않게 한다.
    """
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return _CODE_SLOT.format(len(codes) - 1)

    # 1) 코드 스팬을 자리표시자로 치환 (백틱 1개 이상 대응)
    text = re.sub(r"`([^`]+)`", stash, text)

    # 2) 남은 본문 이스케이프 — 코드 블록 안 `#include <stdio.h>` 가
    #    태그로 먹히는 사고를 여기서 막는다
    text = html.escape(text, quote=False)

    # 3) 인라인 이미지 — 링크보다 먼저. 문단 전체가 그림인 경우는
    #    parse_blocks 가 섬네일로 처리하므로 여기 오지 않는다.
    text = re.sub(
        r'!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)',
        lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" '
                  f'alt="{m.group(1)}" class="inline-img" loading="lazy">',
        text)

    # 4) 링크  [글](대상)
    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        href = rewrite_href(url)
        ext = ' class="external"' if href.startswith(("http://", "https://")) else ""
        return f'<a href="{html.escape(href, quote=True)}"{ext}>{label}</a>'

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)

    # 5) 볼드 → strong, 이탤릭 → em (볼드를 먼저)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<i>\1</i>", text)

    # 6) 실측 표식
    if mark_measured:
        text = re.sub(r"(실측(?:\s*예)?)\s*:",
                      r'<span class="meas">\1</span>', text)

    # 7) 코드 스팬 복원
    for i, c in enumerate(codes):
        text = text.replace(
            _CODE_SLOT.format(i), f"<code>{html.escape(c, quote=False)}</code>"
        )
    return text


# ════════════════════════════════════════════════════════════════════
#  블록 파싱
# ════════════════════════════════════════════════════════════════════

@dataclass
class Block:
    kind: str                      # h1 h2 h3 h4 p pre table ul quote hr ambox mis
    html: str = ""
    text: str = ""                 # 제목의 원문 (목차·앵커용)
    level: int = 0
    anchor: str = ""


FENCE_RE = re.compile(r"^(\s*)```\s*([\w+-]*)\s*$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
HR_RE = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")
LI_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
# 그림: 문단 전체가 이미지 하나인 경우만 섬네일로 만든다.
#   ![캡션](../fig/x.svg)            오른쪽 띄움 (기본)
#   ![캡션](../fig/x.svg "wide")     본문 너비 전체
#   ![캡션](../fig/x.svg "left")     왼쪽 띄움
# 제목 인자는 GitHub 에서 툴팁이 되므로 양쪽에서 깨지지 않는다.
FIG_RE = re.compile(r'^!\[(?P<cap>[^\]]*)\]\((?P<src>\S+?)(?:\s+"(?P<opt>[^"]*)")?\)\s*$')


def render_figure(cap: str, src: str, opt: str, base: Path) -> str:
    """그림 하나를 위키 섬네일 틀로 감싼다.

    SVG 는 파일 내용을 그대로 페이지에 심는다(<img> 가 아니라).
    그래야 페이지의 색 토큰이 도형에 닿아서 다크 모드에서도 선과 글자가 보인다.
    <img> 로 걸면 SVG 가 별도 문서로 격리돼 페이지 CSS 가 적용되지 않는다.
    """
    cls = {"wide": "tnone", "left": "tleft", "none": "tnone"}.get((opt or "").strip(), "tright")
    target = (base / src).resolve()

    if target.suffix.lower() == ".svg" and target.is_file():
        raw = target.read_text(encoding="utf-8")
        raw = re.sub(r"<\?xml[^>]*\?>\s*", "", raw)          # 선언 제거
        raw = re.sub(r"<!DOCTYPE[^>]*>\s*", "", raw, flags=re.I)
        if "role=" not in raw[:400]:
            raw = raw.replace("<svg", '<svg role="img"', 1)
        if "aria-label" not in raw[:400] and cap:
            raw = raw.replace("<svg", f'<svg aria-label="{html.escape(cap, quote=True)}"', 1)
        media = raw
    else:
        if not target.is_file():
            print(f"  ⚠ 그림 없음: {src} (기준 {base})", file=sys.stderr)
        media = (f'<img src="{html.escape(src, quote=True)}" '
                 f'alt="{html.escape(cap, quote=True)}" loading="lazy">')

    caption = f'<div class="thumbcaption">{inline(cap)}</div>' if cap else ""
    return (f'<div class="thumb {cls}"><div class="thumbinner">'
            f'{media}{caption}</div></div>')


def dedent(lines: list[str], n: int) -> list[str]:
    out = []
    for ln in lines:
        out.append(ln[n:] if len(ln) >= n and ln[:n].strip() == "" else ln.lstrip())
    return out


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse_table(lines: list[str], i: int) -> tuple[str, int]:
    header = split_row(lines[i])
    aligns_raw = split_row(lines[i + 1])
    aligns = []
    for a in aligns_raw:
        if a.startswith(":") and a.endswith(":"):
            aligns.append("center")
        elif a.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("")
    j = i + 2
    rows = []
    while j < len(lines) and "|" in lines[j] and lines[j].strip():
        rows.append(split_row(lines[j]))
        j += 1

    def cell(tag: str, val: str, idx: int) -> str:
        style = f' style="text-align:{aligns[idx]}"' if idx < len(aligns) and aligns[idx] else ""
        return f"<{tag}{style}>{inline(val)}</{tag}>"

    out = ['<div class="table-scroll"><table class="wikitable">', "<tr>"]
    out += [cell("th", h, k) for k, h in enumerate(header)]
    out.append("</tr>")
    for r in rows:
        out.append("<tr>")
        out += [cell("td", c, k) for k, c in enumerate(r)]
        out.append("</tr>")
    out.append("</table></div>")
    return "\n".join(out), j


def parse_list(lines: list[str], i: int, base: Path | None = None) -> tuple[str, int]:
    """목록 하나를 소비한다. 항목 안의 이어지는 들여쓴 줄은 재귀로 파싱해서
    코드펜스·표·문단이 항목 안에서도 살아나게 한다."""
    base = len(LI_RE.match(lines[i]).group(1))
    items: list[list[str]] = []
    j = i
    while j < len(lines):
        m = LI_RE.match(lines[j])
        if m and len(m.group(1)) == base:
            items.append([m.group(2)])
            j += 1
            continue
        if not lines[j].strip():
            # 빈 줄: 다음 줄이 이 항목의 연속이면 항목에 포함
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and items:
                ind = len(lines[k]) - len(lines[k].lstrip())
                nxt = LI_RE.match(lines[k])
                if ind > base or (nxt and len(nxt.group(1)) > base):
                    items[-1].append("")
                    j += 1
                    continue
            break
        ind = len(lines[j]) - len(lines[j].lstrip())
        if ind > base and items:
            items[-1].append(lines[j][base:])
            j += 1
            continue
        break

    out = ["<ul>"]
    for item in items:
        first, rest = item[0], item[1:]
        if any(ln.strip() for ln in rest):
            # 항목 안에서도 ⚠·실측 승격이 동작하게 promote 를 거친다.
            # promote 는 h2 상태를 쓰지만 목록 안에는 제목이 없으므로 영향이 없다.
            inner = promote(parse_blocks(dedent(rest, 2), base))
            body = f"{inline(first)}\n" + "\n".join(b.html for b in inner)
        else:
            body = inline(first)
        out.append(f"<li>{body}</li>")
    out.append("</ul>")
    return "\n".join(out), j


def parse_blocks(lines: list[str], base: Path | None = None) -> list[Block]:
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        # 코드펜스 (들여쓴 것 포함)
        m = FENCE_RE.match(line)
        if m:
            indent, lang = len(m.group(1)), m.group(2)
            body: list[str] = []
            i += 1
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                body.append(lines[i][indent:] if len(lines[i]) > indent else lines[i].lstrip())
                i += 1
            i += 1  # 닫는 펜스
            code = html.escape("\n".join(body), quote=False)
            cls = f' class="lang-{lang}"' if lang else ""
            blocks.append(Block("pre", f"<pre><code{cls}>{code}</code></pre>"))
            continue

        # 제목
        m = HEAD_RE.match(line)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            blocks.append(Block(f"h{lvl}", f"<h{lvl}>{inline(txt)}</h{lvl}>",
                                text=txt, level=lvl))
            i += 1
            continue

        # 그림 (문단 전체가 이미지 하나일 때만)
        m = FIG_RE.match(line.strip())
        if m and base is not None:
            blocks.append(Block("fig", render_figure(
                m.group("cap"), m.group("src"), m.group("opt") or "", base)))
            i += 1
            continue

        # 수평선
        if HR_RE.match(line):
            blocks.append(Block("hr", "<hr>"))
            i += 1
            continue

        # 표 (들여쓴 것 포함)
        if "|" in line and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            h, i = parse_table(lines, i)
            blocks.append(Block("table", h))
            continue

        # 인용
        if line.lstrip().startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            q = "\n".join(buf)
            blocks.append(Block("quote", f'<blockquote>{inline(q.replace(chr(10), " "))}</blockquote>',
                                text=q))
            continue

        # 목록
        if LI_RE.match(line):
            h, i = parse_list(lines, i, base)
            blocks.append(Block("ul", h))
            continue

        # 문단
        buf = []
        while i < len(lines) and lines[i].strip():
            nxt = lines[i]
            if (
                HEAD_RE.match(nxt) or FENCE_RE.match(nxt) or HR_RE.match(nxt)
                or LI_RE.match(nxt) or nxt.lstrip().startswith(">")
                or ("|" in nxt and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]))
            ):
                if buf:
                    break
            buf.append(nxt.strip())
            i += 1
        if buf:
            t = " ".join(buf)
            blocks.append(Block("p", f"<p>{inline(t)}</p>", text=t))
    return blocks


# ════════════════════════════════════════════════════════════════════
#  상자 승격
# ════════════════════════════════════════════════════════════════════

MEASURED_RE = re.compile(r"실측(?:\s*예)?\s*:")


def promote(blocks: list[Block]) -> list[Block]:
    """문단을 위키 상자로 올린다.

      ⚠ 로 시작하는 문단        → 주의 상자
      실측: 을 포함하는 문단     → 실측 상자
      「흔한 오해」 절의 h3      → 오해 상자 (다음 h2/h3 까지의 내용을 감싼다)

    제목과 목록 항목은 건드리지 않는다 — 「스텝당 각도를 실측하기」 같은
    제목이 상자로 바뀌는 사고를 막기 위한 것이다.
    """
    out: list[Block] = []
    in_mis = False          # 「흔한 오해」 절 안인가
    mis_open = False        # 오해 상자가 열려 있는가

    def close_mis():
        nonlocal mis_open
        if mis_open:
            out.append(Block("raw", "</div>"))
            mis_open = False

    for b in blocks:
        if b.kind == "h2":
            close_mis()
            in_mis = b.text.strip() in ("흔한 오해", "흔한 오해와 함정")
            out.append(b)
            continue

        if b.kind == "h3" and in_mis:
            close_mis()
            # 제목을 상자 안에 h3 그대로 남긴다. 그래야 render_page 가
            # id 를 붙이고 목차에도 올려서, 같은 문서 안의 앵커 링크가 살아 있다.
            out.append(Block("raw", '<div class="mis">'))
            out.append(b)
            mis_open = True
            continue

        if b.kind in ("h1", "h3", "h4", "hr"):
            close_mis()
            out.append(b)
            continue

        if b.kind == "p":
            t = b.text
            if t.startswith("⚠"):
                body = inline(t.lstrip("⚠ ").strip())
                out.append(Block("raw",
                    f'<div class="ambox ambox-warn"><span class="ambox-tag">주의</span>{body}</div>'))
                continue
            if MEASURED_RE.search(t):
                # 문단이 「실측:」으로 시작하면 그 라벨은 지운다 —
                # 상자 머리의 태그가 이미 같은 말을 하고 있다.
                # 문장 중간에 있는 경우는 그대로 둔다. 어디서부터가 실측인지
                # 알려주는 구실을 하기 때문이다.
                t2 = re.sub(r"^실측(?:\s*예)?\s*:\s*", "", t)
                body = inline(t2, mark_measured=False)
                out.append(Block("raw",
                    f'<div class="ambox ambox-measured"><span class="ambox-tag">실측</span>{body}</div>'))
                continue
            out.append(b)          # 이미 parse_blocks 에서 <p> 로 채워져 있다
            continue

        out.append(b)

    close_mis()
    return out


# ════════════════════════════════════════════════════════════════════
#  페이지 조립
# ════════════════════════════════════════════════════════════════════

def slug(text: str) -> str:
    """제목 → 앵커. GitHub 의 규약(소문자화 · 구두점 제거 · 공백→하이픈)과 맞춘다.

    같은 마크다운이 GitHub 에서도, 이 사이트에서도 같은 앵커를 갖게 하려는 것이다.
    맞추지 않으면 `[...](TLS-X509.md#시계가-틀려도-tls-는-된다)` 같은
    링크가 한쪽에서만 동작한다."""
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[`*\[\]()#|:,.·「」/]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s.lower() or "sec"


@dataclass
class Page:
    src: Path
    chapter: str                   # 디렉터리 이름 (영상 · 압축 …)
    name: str                      # 파일 이름 (확장자 없음)
    title: str = ""
    lead: str = ""                 # 첫 인용 = 한 줄 정의
    body: str = ""
    toc: list[tuple[int, str, str]] = field(default_factory=list)
    out_rel: str = ""


def render_page(p: Page, blocks: list[Block]) -> None:
    """블록을 본문 HTML 로 조립하고, 그 과정에서 목차를 모은다.
    목차 항목은 (수준, 번호, 앵커, 표시할 제목) 네 값이다."""
    seen: dict[str, int] = {}
    parts: list[str] = []
    toc: list[tuple[int, str, str, str]] = []
    num2 = num3 = 0

    for b in blocks:
        if b.kind == "h1":
            p.title = b.text
            continue

        # 파일 맨 앞의 인용 = 한 줄 정의. 머리글로 올린다.
        if b.kind == "quote" and not p.lead and not parts:
            p.lead = inline(b.text.replace("\n", " "))
            continue

        if b.kind in ("h2", "h3", "h4"):
            lvl = int(b.kind[1])
            a = slug(b.text)
            if a in seen:
                seen[a] += 1
                a = f"{a}-{seen[a]}"
            else:
                seen[a] = 0

            if lvl == 2:
                num2 += 1
                num3 = 0
                label = str(num2)
            elif lvl == 3:
                num3 += 1
                label = f"{num2}.{num3}"
            else:
                label = ""

            if lvl in (2, 3):
                toc.append((lvl, label, a, b.text))

            parts.append(
                f'<{b.kind} id="{html.escape(a, quote=True)}">{inline(b.text)}</{b.kind}>'
            )
            continue

        if b.kind == "quote":
            parts.append(f'<blockquote>{inline(b.text.replace(chr(10), " "))}</blockquote>')
            continue

        parts.append(b.html)

    p.toc = toc
    p.body = "\n".join(parts)


# ════════════════════════════════════════════════════════════════════
#  README 에서 단계 구성 읽기
# ════════════════════════════════════════════════════════════════════

# 사이드바·둘러보기 상자에 올릴 절. 번호가 붙은 단계와 아래 둘만 올린다.
# 「여기서 시작」처럼 안내 목적으로 문서를 링크하는 절이 통째로
# 사이드바 항목이 되는 것을 막기 위한 것이다.
PORTAL_EXTRA = {"분야를 가로지르는 것", "페이지 형식"}


def is_portal(title: str) -> bool:
    return bool(re.match(r"^\d+\.", title.strip())) or title.strip() in PORTAL_EXTRA


def read_index() -> list[tuple[str, list[tuple[str, str]]]]:
    """README.md 의 `## N. 제목` 과 표 안의 링크를 읽어 단계 구성을 만든다.
    사이드바 · 둘러보기 상자 · 대문이 모두 이 결과에서 나온다."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    stages: list[tuple[str, list[tuple[str, str]]]] = []
    cur_title, cur_items, seen = None, [], set()
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            if cur_title:
                stages.append((cur_title, cur_items))
            cur_title, cur_items, seen = m.group(1), [], set()
            continue
        for label, url in re.findall(r"\[([^\]]+)\]\((docs/[^)]+\.md)\)", line):
            if url in seen:
                continue
            seen.add(url)
            cur_items.append((re.sub(r"[`*]", "", label), url))
    if cur_title:
        stages.append((cur_title, cur_items))
    return [(t, it) for t, it in stages if it and is_portal(t)]


# ════════════════════════════════════════════════════════════════════
#  템플릿
# ════════════════════════════════════════════════════════════════════

def doc_count(stages) -> int:
    """단계 전체에서 유일한 문서 수. 같은 문서가 두 단계에 실려도 한 번만 센다.
    `_템플릿.md` 는 형식 설명이므로 편수에서 뺀다."""
    urls = {u for _, items in stages for _, u in items}
    return len({u for u in urls if not u.rsplit("/", 1)[-1].startswith("_")})


def rel(from_rel: str, to_rel: str) -> str:
    depth = from_rel.count("/")
    return ("../" * depth) + to_rel


def sidebar(stages, cur_rel: str, cur_src: str) -> str:
    out = [
        f'<div id="mw-panel">',
        f'<div class="wiki-logo"><a href="{rel(cur_rel, "index.html")}">{html.escape(SITE_NAME)}</a></div>',
    ]
    for title, items in stages:
        short = re.sub(r"^\d+\.\s*", "", title)
        out.append('<div class="portal">')
        out.append(f"<h3>{html.escape(short)}</h3><ul>")
        for label, url in items:
            href = rel(cur_rel, url[len("docs/"):].replace(".md", ".html"))
            cls = ' class="cur"' if url == cur_src else ""
            out.append(f'<li{cls}><a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></li>')
        out.append("</ul></div>")
    out.append('<div class="portal"><h3>도구</h3><ul>')
    out.append(f'<li><a href="{rel(cur_rel, "index.html")}">대문</a></li>')
    out.append(f'<li><a href="{BLOG_URL}" class="external">블로그</a></li>')
    out.append(f'<li><a href="{REPO_URL}" class="external">원본 저장소</a></li>')
    out.append("</ul></div></div>")
    return "\n".join(out)


def navbox(stages, cur_rel: str) -> str:
    total = doc_count(stages)
    out = ['<table class="navbox">',
           f'<tr><th class="navbox-title" colspan="2">{html.escape(SITE_NAME)} — {total}편</th></tr>']
    for title, items in stages:
        short = re.sub(r"^\d+\.\s*", "", title)
        out.append(f'<tr><th class="navbox-group">{html.escape(short)}</th><td><ul>')
        for label, url in items:
            href = rel(cur_rel, url[len("docs/"):].replace(".md", ".html"))
            out.append(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></li>')
        out.append("</ul></td></tr>")
    out.append("</table>")
    return "\n".join(out)


def toc_html(toc) -> str:
    """위키 목차 상자. 항목이 둘 미만이면 만들지 않는다."""
    if len(toc) < 2:
        return ""
    out = ['<div id="toc"><div class="toctitle"><h2>목차</h2></div><ul>']
    depth = 2
    for lvl, label, anchor, text in toc:
        while lvl > depth:
            out.append("<ul>")
            depth += 1
        while lvl < depth:
            out.append("</ul>")
            depth -= 1
        out.append(f'<li><a href="#{html.escape(anchor, quote=True)}">'
                   f'<span class="tocnumber">{label}</span> {inline(text)}</a></li>')
    while depth > 2:
        out.append("</ul>")
        depth -= 1
    out.append("</ul></div>")
    return "\n".join(out)


def git_date(path: Path) -> str:
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cd", "--date=format:%Y년 %m월 %d일",
                            "--", str(path.relative_to(ROOT))],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


SHELL = """<title>{title}</title>
<link rel="stylesheet" href="{css}">
<div class="mw-page">
{sidebar}
<div class="mw-body-wrap">
<div id="mw-head">
  <div class="mw-crumb">{crumb}</div>
  <div class="mw-search">
    <input id="q" type="search" placeholder="검색" autocomplete="off"
           aria-label="문서 검색" spellcheck="false">
    <ul id="qr" hidden></ul>
  </div>
</div>
<div id="content"><div class="mw-inner">
<h1 id="firstHeading">{h1}</h1>
{sitesub}
{lead}
{toc}
{body}
{navbox}
<div class="catlinks"><b>분류</b>: <ul>{cats}</ul></div>
</div></div>
<div id="footer">
<p>{footer}</p>
<ul><li>원본: <a href="{src_url}" class="external">{src_rel}</a> ·
이 사이트는 <a href="{repo}" class="external">ipcam-notes</a> 의 마크다운에서
<code>tools/build_wiki.py</code> 로 생성됩니다.</li>
<li>개인 기술 노트입니다. 위키백과·위키미디어 재단과 관련이 없으며 문서 형식만 참고했습니다.</li></ul>
</div>
</div></div>
<script>window.__PAGES__ = {pages};</script>
<script src="{js}"></script>
"""


def build_page(p: Page, stages, pages_json: str) -> str:
    # 머리글: 위키처럼 제목을 볼드로 앞세우고 한 줄 정의를 이어 붙인다
    t = html.escape(p.title)
    lead = f'<p class="lead"><b>{t}</b> — {p.lead}</p>' if p.lead else f'<p class="lead"><b>{t}</b></p>'
    cats = "".join(
        f'<li><a href="{rel(p.out_rel, "index.html")}">{html.escape(c)}</a></li>'
        for c in (p.chapter, "IP카메라 기술 노트")
    )
    date = git_date(p.src)
    footer = (f"이 문서는 {date}에 마지막으로 편집되었습니다." if date
              else "편집 이력을 확인할 수 없습니다.")
    crumb = (f'<a href="{rel(p.out_rel, "index.html")}">{html.escape(SITE_NAME)}</a>'
             f' &rsaquo; {html.escape(p.chapter)}')
    return SHELL.format(
        crumb=crumb,
        title=f"{p.title} — {SITE_NAME}",
        css=rel(p.out_rel, "style.css"),
        js=rel(p.out_rel, "search.js"),
        sidebar=sidebar(stages, p.out_rel, f"docs/{p.chapter}/{p.name}.md"),
        h1=html.escape(p.title),
        sitesub=f'<div class="siteSub">{html.escape(p.chapter)}</div>',
        lead=lead,
        toc=toc_html(p.toc),
        body=p.body,
        navbox=navbox(stages, p.out_rel),
        cats=cats,
        footer=footer,
        src_url=f"{REPO_URL}/blob/main/docs/{p.chapter}/{p.name}.md",
        src_rel=f"docs/{p.chapter}/{p.name}.md",
        repo=REPO_URL,
        pages=pages_json,
    )


def build_index(stages, pages_json: str) -> str:
    md = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    blocks = promote(parse_blocks(md, base=ROOT))
    p = Page(src=ROOT / "README.md", chapter="대문", name="index", out_rel="index.html")
    render_page(p, blocks)
    total = doc_count(stages)
    body = p.body.replace('href="docs/', 'href="')
    body = re.sub(r'href="([^"]*)\.md"', r'href="\1.html"', body)
    lead = (f'<p class="lead"><b>{html.escape(SITE_NAME)}</b> — IP카메라를 만들 때 지나가는 '
            f'기술을 항목별로 정리한 노트다. 현재 {total}편.</p>')
    return SHELL.format(
        crumb=f"전체 {total}편",
        title=SITE_NAME,
        css="style.css",
        js="search.js",
        sidebar=sidebar(stages, "index.html", ""),
        h1=html.escape(SITE_NAME),
        sitesub="",
        lead=lead,
        toc=toc_html(p.toc),
        body=body,
        navbox=navbox(stages, "index.html"),
        cats='<li><a href="index.html">대문</a></li>',
        footer=f"전체 {total}편. 마지막 생성: 빌드 시각 기준.",
        src_url=f"{REPO_URL}/blob/main/README.md",
        src_rel="README.md",
        repo=REPO_URL,
        pages=pages_json,
    )


SEARCH_JS = r"""// 사이드바 검색 — 페이지 목록을 훑어 제목으로 걸러낸다. 서버가 필요 없다.
(function () {
  var q = document.getElementById('q'), r = document.getElementById('qr');
  if (!q || !r || !window.__PAGES__) return;
  var pages = window.__PAGES__, depth = (location.pathname.match(/\//g) || []).length;

  function base() {
    var d = document.querySelector('link[rel=stylesheet]');
    return d ? d.getAttribute('href').replace('style.css', '') : '';
  }

  function render(list) {
    if (!list.length) { r.hidden = true; r.innerHTML = ''; return; }
    r.innerHTML = list.slice(0, 10).map(function (p) {
      return '<li><a href="' + base() + p.u + '">' + p.t +
             '<span class="qr-ch">' + p.c + '</span></a></li>';
    }).join('');
    r.hidden = false;
  }

  q.addEventListener('input', function () {
    var v = q.value.trim().toLowerCase();
    if (!v) { render([]); return; }
    render(pages.filter(function (p) {
      return (p.t + ' ' + p.c).toLowerCase().indexOf(v) !== -1;
    }));
  });
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { q.value = ''; render([]); q.blur(); }
    if (e.key === 'Enter') { var a = r.querySelector('a'); if (a) location.href = a.href; }
  });
  document.addEventListener('click', function (e) {
    if (!r.contains(e.target) && e.target !== q) render([]);
  });
})();
"""


# ════════════════════════════════════════════════════════════════════
#  main
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="마크다운 노트를 위키 스타일 사이트로 변환")
    ap.add_argument("--out", default="site", help="출력 디렉터리 (기본: site)")
    ap.add_argument("--serve", action="store_true", help="생성 후 미리보기 서버 실행")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    out = ROOT / args.out
    if not DOCS.is_dir():
        print(f"오류: {DOCS} 가 없습니다", file=sys.stderr)
        return 1
    if not CSS_SRC.is_file():
        print(f"오류: {CSS_SRC} 가 없습니다", file=sys.stderr)
        return 1

    stages = read_index()
    if not stages:
        print("오류: README.md 에서 단계 구성을 읽지 못했습니다", file=sys.stderr)
        return 1

    # 페이지 수집. `_템플릿.md` 도 포함한다 — README 와 사이드바가 가리키고 있고,
    # 문서 형식 자체가 위키의 내용이기도 하다. GitHub Pages 가 밑줄 경로를
    # 무시하지 않도록 .nojekyll 을 함께 쓴다.
    srcs = sorted(DOCS.rglob("*.md"))
    pages: list[Page] = []
    for src in srcs:
        r = src.relative_to(DOCS)
        chapter = r.parts[0] if len(r.parts) > 1 else "일반"
        p = Page(src=src, chapter=chapter, name=src.stem)
        p.out_rel = (f"{chapter}/{src.stem}.html" if len(r.parts) > 1 else f"{src.stem}.html")
        pages.append(p)

    # 변환
    for p in pages:
        blocks = promote(parse_blocks(
            p.src.read_text(encoding="utf-8").splitlines(), base=p.src.parent))
        render_page(p, blocks)
        if not p.title:
            p.title = p.name

    pages_json = json.dumps(
        [{"t": p.title, "c": p.chapter, "u": p.out_rel} for p in pages],
        ensure_ascii=False, separators=(",", ":"),
    )

    # 쓰기
    out.mkdir(parents=True, exist_ok=True)
    (out / "style.css").write_text(CSS_SRC.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "search.js").write_text(SEARCH_JS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages 가 _ 파일을 지우지 않게

    # SVG 가 아닌 그림(png 등)은 파일째 복사한다. SVG 는 본문에 심기므로 불필요.
    import shutil
    figdir = DOCS / "fig"
    if figdir.is_dir():
        for f in figdir.rglob("*"):
            if f.is_file() and f.suffix.lower() != ".svg":
                d = out / "fig" / f.relative_to(figdir)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d)

    for p in pages:
        dst = out / p.out_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(build_page(p, stages, pages_json), encoding="utf-8")

    (out / "index.html").write_text(build_index(stages, pages_json), encoding="utf-8")

    n_html = len(list(out.rglob("*.html")))
    print(f"입력 {len(srcs)}파일 → 출력 {n_html}쪽 "
          f"(문서 {doc_count(stages)}편 + 템플릿 + 대문)  →  {out}")
    for title, items in stages:
        print(f"  {title}: {len(items)}")

    if args.serve:
        import http.server, socketserver, functools
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
        with socketserver.TCPServer(("127.0.0.1", args.port), h) as srv:
            print(f"\nhttp://127.0.0.1:{args.port}/  (Ctrl+C 로 종료)")
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
