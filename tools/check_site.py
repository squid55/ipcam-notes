#!/usr/bin/env python3
"""생성된 사이트를 검사한다. 변환이 조용히 망가지는 경우를 잡는 것이 목적이다.

    python3 tools/check_site.py [--out site]

검사 항목
    1. 내부 링크가 실제 파일·앵커를 가리키는가
    2. 원본의 코드 블록 수가 보존됐는가
    3. 코드 안의 <...> 가 태그로 먹히지 않았는가
    4. 표 수가 보존됐는가
    5. 변환되지 않은 마크다운이 본문에 남아 있는가
    6. 승격된 상자 수가 원본의 표시 수와 맞는가
    7. 필수 자산(style.css · search.js)이 있는가\n    8. 원본 본문의 낱말이 출력에 다 남아 있는가 (조용한 유실 탐지)

종료 코드 0 = 통과, 1 = 실패.
"""

from __future__ import annotations

import argparse
import html as html_mod
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def strip_pre(s: str) -> tuple[str, list[str]]:
    """<pre> 블록과 <code> 스팬을 떼어낸다.

    코드 안에는 마크다운처럼 보이는 문자열이 정당하게 들어 있다 —
    `**` `##` `](x.md)` 같은 것들. 검사 5번(변환 누락)이 그걸 보고
    오탐을 내지 않게 여기서 미리 걷어낸다."""
    pres = re.findall(r"<pre><code[^>]*>(.*?)</code></pre>", s, flags=re.S)
    s = re.sub(r"<pre><code[^>]*>.*?</code></pre>", "\x00PRE\x00", s, flags=re.S)
    s = re.sub(r"<code[^>]*>.*?</code>", "\x00CODE\x00", s, flags=re.S)
    return s, pres


FENCE = re.compile(r"^\s*```")
TOKEN = re.compile(r"[0-9A-Za-z_]{2,}|[\uac00-\ud7a3]{2,}")


def md_text(md: str) -> str:
    """마크다운에서 눈에 보이는 본문만 남긴다.

    코드 블록은 따로 세므로 제외하고, 링크는 표시 글자만 남긴다
    (URL 은 href 로 가므로 본문 텍스트에 나타나지 않는다)."""
    out, in_fence = [], False
    for ln in md.splitlines():
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append(ln)
    t = "\n".join(out)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)   # 링크 → 표시 글자만
    t = re.sub(r"^\s*\|?[\s:|-]*-[\s:|-]*\|.*$", "", t, flags=re.M)  # 표 구분선
    return t


def tokens(t: str) -> list[str]:
    return TOKEN.findall(t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    args = ap.parse_args()
    site = ROOT / args.out

    if not site.is_dir():
        print(f"실패: {site} 가 없습니다. 먼저 build_wiki.py 를 돌리세요.", file=sys.stderr)
        return 1

    errors: list[str] = []
    warns: list[str] = []
    pages = sorted(site.rglob("*.html"))

    # ── 7. 자산
    for asset in ("style.css", "search.js", ".nojekyll"):
        if not (site / asset).is_file():
            errors.append(f"자산 없음: {asset}")

    # ── 앵커 목록을 먼저 수집
    anchors: dict[Path, set[str]] = {}
    for f in pages:
        s = f.read_text(encoding="utf-8")
        anchors[f] = set(re.findall(r'id="([^"]+)"', s))

    # ── 1. 링크 검사
    n_links = 0
    for f in pages:
        s = f.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"]+)"', s):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            n_links += 1
            path, _, frag = href.partition("#")
            if not path:
                if frag and frag not in anchors[f]:
                    errors.append(f"{f.relative_to(site)}: 앵커 없음 #{frag}")
                continue
            target = (f.parent / unquote(path)).resolve()
            if not target.is_file():
                errors.append(f"{f.relative_to(site)}: 링크 대상 없음 {href}")
            elif frag and target in anchors and frag not in anchors[target]:
                warns.append(f"{f.relative_to(site)}: 앵커 없음 {href}")

    # ── 원본과 대조
    srcs = sorted(DOCS.rglob("*.md"))
    tot_src_fence = tot_out_pre = 0
    tot_src_table = tot_out_table = 0
    tot_src_warn = tot_out_warn = 0
    tot_src_meas = tot_out_meas = 0

    for src in srcs:
        r = src.relative_to(DOCS)
        out = site / (str(r.with_suffix(".html")))
        if not out.is_file():
            errors.append(f"출력 없음: {r}")
            continue
        md = src.read_text(encoding="utf-8")
        s = out.read_text(encoding="utf-8")
        body, pres = strip_pre(s)

        # 2. 코드 블록 수
        n_fence = md.count("```") // 2
        tot_src_fence += n_fence
        tot_out_pre += len(pres)
        if len(pres) != n_fence:
            errors.append(f"{r}: 코드 블록 {n_fence} → {len(pres)} (불일치)")

        # 3. 코드 안 <...> 보존
        src_inc = len(re.findall(r"#include\s*<", md))
        out_inc = sum(len(re.findall(r"#include\s*&lt;", p)) for p in pres)
        if src_inc != out_inc:
            errors.append(f"{r}: #include <...> {src_inc} → {out_inc} (이스케이프 유실)")

        # 4. 표
        n_tbl = len(re.findall(r"^\s*\|?[\s:|-]*-[\s:|-]*\|", md, flags=re.M))
        tot_src_table += n_tbl
        n_out_tbl = s.count('<table class="wikitable">')
        tot_out_table += n_out_tbl
        if n_out_tbl != n_tbl:
            warns.append(f"{r}: 표 {n_tbl} → {n_out_tbl}")

        # 5. 변환 안 된 마크다운이 본문에 남았는가
        plain = re.sub(r"<[^>]+>", "", body)
        plain = html_mod.unescape(plain)
        for pat, label in (
            (r"\*\*[^*\n]{1,60}\*\*", "볼드 **"),
            (r"^\s*#{2,4}\s", "제목 ##"),
            (r"\]\([^)]*\.md\)", "링크 .md"),
        ):
            m = re.search(pat, plain, flags=re.M)
            if m:
                errors.append(f"{r}: 변환 안 된 {label} → {m.group(0)[:40]!r}")

        # 6. 승격 상자
        n_warn_src = len(re.findall(r"^⚠", md, flags=re.M))
        n_warn_out = s.count("ambox-warn")
        tot_src_warn += n_warn_src
        tot_out_warn += n_warn_out
        if n_warn_out < n_warn_src:
            warns.append(f"{r}: ⚠ 상자 {n_warn_src} → {n_warn_out}")

        n_meas_out = s.count("ambox-measured")
        tot_out_meas += n_meas_out
        tot_src_meas += len(re.findall(r"실측(?:\s*예)?\s*:", md))

        # 8. 텍스트 보존 — 원본의 낱말이 출력에 다 있는가.
        #    목록 항목 안의 문단이 통째로 사라지는 사고를 여기서 잡는다.
        #    (문장이 없어져도 링크·코드·표 개수는 그대로라 다른 검사로는 안 잡힌다)
        src_tok = tokens(md_text(md))
        out_tok = set(tokens(html_mod.unescape(re.sub(r"<[^>]+>", " ", s))))
        missing = [w for w in dict.fromkeys(src_tok) if w not in out_tok]
        if missing:
            errors.append(
                f"{r}: 본문 유실 낱말 {len(missing)}개 → "
                + ", ".join(repr(w) for w in missing[:6])
            )

    # ── 결과
    print(f"페이지        {len(pages)}쪽")
    print(f"내부 링크     {n_links}개")
    print(f"코드 블록     원본 {tot_src_fence} → 출력 {tot_out_pre}")
    print(f"표            원본 {tot_src_table} → 출력 {tot_out_table}")
    print(f"⚠ 상자        원본 표시 {tot_src_warn} → 승격 {tot_out_warn}")
    print(f"실측 상자     원본 표시 {tot_src_meas} → 승격 {tot_out_meas}")
    print(f"본문 보존     낱말 유실 0개 기준으로 전 페이지 대조")

    if warns:
        print(f"\n경고 {len(warns)}건")
        for w in warns[:15]:
            print(f"  · {w}")
        if len(warns) > 15:
            print(f"  … 외 {len(warns) - 15}건")

    if errors:
        print(f"\n실패 {len(errors)}건")
        for e in errors[:25]:
            print(f"  ✗ {e}")
        if len(errors) > 25:
            print(f"  … 외 {len(errors) - 25}건")
        return 1

    print("\n통과 — 오류 0건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
