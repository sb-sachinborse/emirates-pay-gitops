.PHONY: run test smoke build up down

run:            ## run locally on :8080 (development mode, SQLite in ./data)
	python3 -m flask --app app.wsgi run --port 8080

test:           ## unit + integration tests
	python3 -m unittest discover -s tests -v

smoke:          ## end-to-end check against a running instance
	sh scripts/smoke.sh http://localhost:8080

build:
	docker build -t emirates-pay-app:dev --build-arg GIT_SHA=$$(git rev-parse --short HEAD 2>/dev/null || echo local) .

up:
	docker compose up --build -d

down:
	docker compose down -v
