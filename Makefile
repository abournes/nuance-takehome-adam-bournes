PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: setup clips run evaluate clean

## setup: create a virtualenv, install dependencies, create .env, fetch the clips
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	@if [ ! -f .env ] && [ ! -f .env.example ]; then \
	  echo ""; \
	  echo ".env.example is missing too, so there is nothing to copy it from."; \
	  echo "This folder is missing files it shipped with -- re-download the"; \
	  echo "scaffolding from your brief link and start from that unzipped folder"; \
	  echo "rather than copying files into a separate one (that's usually how"; \
	  echo "the hidden files -- .env, .env.example, .gitignore -- go missing)."; \
	  echo ""; \
	  exit 1; \
	fi
	@if [ ! -f .env ]; then cp .env.example .env; echo "created .env from .env.example"; else echo ".env already exists, leaving it alone"; fi
	@$(MAKE) --no-print-directory clips

## clips: download data/clips (~250MB). Idempotent; skips if already present.
clips:
	@set -eu; \
	count=$$(ls data/clips/*.wav 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$$count" = "142" ]; then echo "data/clips already has 142 clips"; exit 0; fi; \
	if [ ! -f .env ] && [ ! -f .env.example ]; then \
	  echo ""; \
	  echo ".env.example is missing too, so there is nothing to copy it from."; \
	  echo "This folder is missing files it shipped with -- re-download the"; \
	  echo "scaffolding from your brief link and start from that unzipped folder"; \
	  echo "rather than copying files into a separate one (that's usually how"; \
	  echo "the hidden files -- .env, .env.example, .gitignore -- go missing)."; \
	  echo ""; \
	  exit 1; \
	fi; \
	if [ ! -f .env ]; then \
	  echo "No .env yet. Run 'cp .env.example .env' and paste in your API key."; \
	  exit 1; \
	fi; \
	ASR_API_KEY=$$(sed -n 's/^[[:space:]]*ASR_API_KEY[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '"'\''\r'); \
	ASR_BASE_URL=$$(sed -n 's/^[[:space:]]*ASR_BASE_URL[[:space:]]*=[[:space:]]*//p' .env | tail -1 | tr -d '"'\''\r'); \
	if [ -z "$${ASR_API_KEY:-}" ] || [ "$$ASR_API_KEY" = "paste-your-key-here" ]; then \
	  echo ""; \
	  echo "Put your API key in .env (ASR_API_KEY), then run 'make clips'."; \
	  echo "It is the only value you need to set."; \
	  echo ""; \
	  exit 1; \
	fi; \
	if [ -z "$${ASR_BASE_URL:-}" ]; then \
	  echo "ASR_BASE_URL is empty. It ships pre-filled in .env.example -- "; \
	  echo "copy that file again if you removed it."; \
	  exit 1; \
	fi; \
	echo "downloading clips (~250MB, once)"; \
	mkdir -p data; \
	set +e; \
	code=$$(curl -fL --progress-bar -w '%{http_code}' \
	  -H "Authorization: Bearer $$ASR_API_KEY" \
	  "$${ASR_BASE_URL%/}/clips" -o data/clips.tar.gz); \
	rc=$$?; set -e; \
	if [ $$rc -ne 0 ]; then \
	  rm -f data/clips.tar.gz; \
	  echo ""; \
	  echo "Clip download failed (curl exit $$rc, HTTP $$code)."; \
	  case "$$code" in \
	    401) echo "  ASR_API_KEY looks wrong. Check the value in .env.";; \
	    000) echo "  Could not reach $$ASR_BASE_URL. Check ASR_BASE_URL and your network.";; \
	    *)   echo "  That is our end, not yours. Get in touch and we'll sort it out.";; \
	  esac; \
	  echo ""; \
	  exit 1; \
	fi; \
	tar -xzf data/clips.tar.gz -C data || { \
	  rm -f data/clips.tar.gz; \
	  echo "Downloaded archive would not extract. Re-run 'make clips'."; \
	  exit 1; \
	}; \
	rm -f data/clips.tar.gz; \
	got=$$(ls data/clips/*.wav 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$$got" != "142" ]; then \
	  echo "Expected 142 clips, got $$got. Re-run 'make clips'."; exit 1; \
	fi; \
	echo "extracted $$got clips to data/clips/"

## run: run the pipeline over data/clips, writing output.json and run_meta.json
run:
	@if [ ! -x $(BIN)/python ]; then \
		echo "No virtualenv yet. Run 'make setup' first."; exit 1; \
	fi
	@if [ ! -f pipeline/__main__.py ]; then \
		echo ""; \
		echo "pipeline/__main__.py is missing -- 'make run' needs it, because it"; \
		echo "runs 'python -m pipeline'. Restore it from git, or write your own:"; \
		echo "    python -m pipeline   ->   writes output.json"; \
		echo ""; \
		exit 1; \
	fi
	@rm -f run_meta.json
	@start=$$(date +%s); \
	set +e; $(BIN)/python -m pipeline; status=$$?; set -e; \
	end=$$(date +%s); \
	elapsed=$$((end - start)); \
	printf '{\n  "run_seconds": %d,\n  "exit_status": %d\n}\n' $$elapsed $$status > run_meta.json; \
	echo ""; \
	echo "pipeline exited $$status after $${elapsed}s -> run_meta.json"; \
	if [ ! -f output.json ]; then echo "WARNING: no output.json was written"; fi; \
	exit $$status

## evaluate: score output.json against the dev references, locally
evaluate:
	@if [ ! -x $(BIN)/python ]; then \
		echo "No virtualenv yet. Run 'make setup' first."; exit 1; \
	fi
	@set -a; [ -f .env ] && . ./.env; set +a; $(BIN)/python scripts/evaluate.py

clean:
	rm -f output.json run_meta.json chunks.json
