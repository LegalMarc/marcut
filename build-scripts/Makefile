SHELL := /bin/bash

.PHONY: smoke verify-app verify-dmg test

test:
	pytest -q

smoke:
	bash scripts/smoke_redaction.sh

verify-app:
	bash scripts/verify_bundle.sh build_swift/MarcutApp.app

verify-dmg:
	bash scripts/verify_bundle.sh MarcutApp-*.dmg

