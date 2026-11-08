#!/usr/bin/env bash
# Build and start the legacy Lending Library (JDK 17+, Maven). Fine payments need a gateway that has no test instance.
set -euo pipefail
cd "$(dirname "$0")"
mvn -q -B package -DskipTests
exec java -cp "target/classes:target/dependency/*" lib.App
