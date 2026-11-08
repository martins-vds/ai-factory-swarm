#!/usr/bin/env bash
# Build and run the monthly billing job (JDK 17+, Maven, access to the Northgate repository).
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -B package
exec java -cp "target/classes:target/dependency/*" billing.BillingJob "$@"
