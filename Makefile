.PHONY: help build live fast test site serve clean deploy-check

help:
	@echo "make build   — rebuild from the local snapshot (cached satellites)"
	@echo "make live    — pull the doc from Google, then rebuild"
	@echo "make fast    — hub only, no satellite crawl"
	@echo "make test    — run the extraction test suite"
	@echo "make serve   — serve dist/ at http://localhost:8000"
	@echo "make links   — health-check 300 links"
	@echo "make clean   — remove build outputs (keeps the database)"

build:
	python3 tools/pipeline.py --satellite-ttl 86400

live:
	python3 tools/pipeline.py --live

fast:                                   # preview build; leaves site/ and dist/ alone
	python3 tools/pipeline.py --no-satellites

links:
	python3 tools/pipeline.py --no-satellites --linkcheck 300

test:
	python3 -m unittest discover -s tests

serve: build
	@echo "→ http://localhost:8000"
	cd dist && python3 -m http.server 8000

clean:
	rm -rf dist site build/data.json build/run.json

deploy-check:
	@test -f dist/index.html && test -f dist/data.json && echo "dist looks deployable"
