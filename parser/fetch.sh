#!/usr/bin/env bash
# Download the pinned sdfz-demo-parser standalone executable (Node.js bundled in,
# no Node install needed) and verify its checksum.
#
# Usage: parser/fetch.sh [install-dir]
# (default: $REASON8_DATA_DIR/tools, or <repo>/data/tools when it is unset)
# Prints the path of the binary on success. Idempotent: does nothing if present.
#
# Upstream publishes no checksums, so SHA256 below was recorded when the version
# was pinned. To bump: change VERSION, set SHA256="", run the script, check the
# hash it prints, and paste it in.
set -euo pipefail

VERSION="5.15.1"
SHA256="0a7dc4f99b9cc9c470b977df3045a4f8e74d720f794de4f6b9ae0c6d744b9cc4"
TARGET="linux-x64"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESTINATION="${1:-${REASON8_DATA_DIR:-$REPO_ROOT/data}/tools}/sdfz-demo-parser-$VERSION"
PARSER_BINARY="$DESTINATION/sdfz-demo-parser"
ARCHIVE="sdfz-demo-parser-$VERSION-$TARGET.tar.gz"
URL="https://github.com/beyond-all-reason/demo-parser/releases/download/v$VERSION/$ARCHIVE"

if [[ -x "$PARSER_BINARY" ]]; then
	echo "$PARSER_BINARY"
	exit 0
fi

temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

curl -fsSL --retry 3 -o "$temporary_directory/$ARCHIVE" "$URL"
actual_sha256="$(sha256sum "$temporary_directory/$ARCHIVE" | cut -d' ' -f1)"
if [[ -z "$SHA256" ]]; then
	echo "SHA256 not pinned; the downloaded archive's hash is: $actual_sha256" >&2
	exit 1
fi
if [[ "$actual_sha256" != "$SHA256" ]]; then
	echo "Checksum mismatch for $ARCHIVE: expected $SHA256, got $actual_sha256" >&2
	exit 1
fi

tar -xzf "$temporary_directory/$ARCHIVE" -C "$temporary_directory" sdfz-demo-parser
mkdir -p "$DESTINATION"
install -m 0755 "$temporary_directory/sdfz-demo-parser" "$PARSER_BINARY"
echo "$PARSER_BINARY"
