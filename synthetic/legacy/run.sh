#!/usr/bin/env bash
# Build and start the legacy Lending Library (JDK 17+). Fine payments need a gateway that has no test instance.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
javac -d build $(find src/main/java -name '*.java')
exec java -cp build lib.App
