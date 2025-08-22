# Repo Fingerprint\nGenerated: 2025-08-21T20:37:26-05:00\nRepo root: /Users/justinadams/Downloads/Context-memory-main\n\n## Recent commits\n(none)\n\n## Uncommitted changes\n(clean or not a git repo)\n\n## Last commit diff (stat)\n(n/a)\n\n## Top-level entries\n- .env.development
- .env.example
- .env.production
- .github
- .gitignore
- .pre-commit-config.yaml
- .qoder
- CHANGELOG.md
- CONTRIBUTING.md
- DEPLOYMENT.md
- Dockerfile
- FRONTEND_REVIEW_REPORT.md
- README.md
- docker-compose.local.yml
- docker-compose.yml
- docs
- infra
- k8s
- pyproject.toml
- pytest.ini
- remote_key
- remote_key.pub
- repo-fingerprint.md
- requirements-dev.txt
- requirements.txt
- scripts
- server
- zen-mcp-server\n\n## Stack indicators\n- Node/TS: no\n- Python pyproject: yes\n- Python requirements: yes\n- Go: no\n- Java Maven: no\n- Java Gradle: no\n- Docker compose: yes\n\n## Language footprint\n2394 py
1156 pyc
  59 md
  50 typed
  44 txt
  42 dist-info/wheel
  42 dist-info/requested
  42 dist-info/record
  42 dist-info/metadata
  42 dist-info/installer
  19 dist-info/licenses/license
  16 yml
  16 pyi
  13 sample
  13 json
  11 tf
   9 sh
   9 html
   7 tpl
   6 so
   6 ps1
   6 exe
   6 dist-info/license
   4 yaml
   4 ini
   3 gitignore
   3 dist-info/licenses/copying
   3 bat
   2 toml
   2 pem\n\n## Tool versions\n- node: v24.5.0
- npm: 11.5.1
- pnpm: 10.14.0
- python3: 
- java: The operation couldn’t be completed. Unable to locate a Java Runtime.\n\n## Auto-detected test commands\n- pytest -q\n
## Flaky repro harness (choose one)
- Python: for i in {1..50}; do pytest -q -k '<pattern>' --maxfail=1 || { echo "Failed on iter $i"; break; }; done\n- Node:   for i in {1..50}; do npx jest -i --runInBand -t '<pattern>' || break; done\n- Go:     for i in {1..50}; do go test -run <TestName> -count=1 ./... || break; done\n
