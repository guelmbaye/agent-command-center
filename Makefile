# Ports surchargeables : 8080 est tres dispute (llama.cpp, XAMPP, Tomcat...).
#   make run PORT=8099
#   make web ACC_API=http://127.0.0.1:8099
PORT ?= 8080
MOCK_PORT ?= 8081
ACC_API ?= http://127.0.0.1:$(PORT)

# Toutes les cibles passent par scripts/dev.py : la syntaxe POSIX
# « VAR=valeur commande » n'existe pas sous cmd.exe, ou make delegue sous
# Windows. Python garantit un comportement identique sur les trois systemes.
PY ?= python

.PHONY: install run run-mock web web-install web-build stack test scenario \
        audit doctor costs teardown fmt

install:
	pip install -r requirements.txt

run:
	$(PY) scripts/dev.py api --port $(PORT) --mock-port $(MOCK_PORT)

run-mock:
	$(PY) scripts/dev.py mock --port $(MOCK_PORT)

web-install:
	$(PY) scripts/dev.py install-web

web:
	$(PY) scripts/dev.py web --api $(ACC_API)

web-build:
	$(PY) scripts/dev.py build --api $(ACC_API)

stack:
	docker compose -f infrastructure/docker/docker-compose.yml up --build

test:
	pytest -q

test-all: test
	$(PY) scripts/dev.py typecheck

scenario:
	$(PY) scripts/run_hero_scenario.py

audit:
	$(PY) scripts/audit_coverage.py

doctor:
	$(PY) scripts/doctor.py --api $(ACC_API) --enterprise http://127.0.0.1:$(MOCK_PORT)

costs:
	./scripts/costs.sh

teardown:
	./scripts/teardown.sh
