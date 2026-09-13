.PHONY: site check serve clean help

OUT ?= site
PORT ?= 8000

help:
	@echo "make site    — docs/ 의 마크다운을 $(OUT)/ 에 위키 스타일 HTML 로 생성"
	@echo "make check   — 생성 결과 검사 (링크 · 코드 블록 · 표 · 본문 유실)"
	@echo "make serve   — 생성하고 http://127.0.0.1:$(PORT)/ 로 미리보기"
	@echo "make clean   — $(OUT)/ 삭제"

site:
	python3 tools/build_wiki.py --out $(OUT)

check: site
	python3 tools/check_site.py --out $(OUT)

serve:
	python3 tools/build_wiki.py --out $(OUT) --serve --port $(PORT)

clean:
	rm -rf $(OUT)
