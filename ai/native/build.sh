#!/usr/bin/env bash
# Build BARb (CircuitAI) from source with the Reason8 command governor and
# live state, for Linux x86-64, without root: a conda-forge GCC 13 toolchain,
# the engine source at the tag of the installed engine and BAR's prebuilt
# static libraries. See docs/reference/in-game.md, "Our own build of BARb's
# library". `reason8 bot build` runs it.
#
#   ai/native/build.sh <work dir> [engine tag] [engine commit]
#
# Leaves the library, stripped, at
# <work dir>/libSkirmishAI.so (with it in build/AI/Skirmish/BARb/data/), and
# <work dir>/reason8_library.json, which says what it was built from: the
# engine tag and commit, and the SHA-256 of the library and of the files in
# ai/native.
#
# Everything downloaded is checked before it runs: micromamba and the
# toolchain packages against the SHA-256 recorded here and in toolchain.lock,
# the sources against the commits recorded here. A different engine tag needs
# its commit as the third argument.
set -euo pipefail

micromamba_version=2.10.0-0
micromamba_sha256=701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd
default_tag=2026.09.03
default_commit=8688dcc2690a8db4e6624dd516ef5da8cf3c5ec8
static_libs_commit=25a1f8685b3e60fc09aa111a70a1f6a8c89c8154

system="$(uname -s) $(uname -m)"
if [ "$system" != "Linux x86_64" ]; then
	echo "build.sh builds on Linux x86_64 only, this is $system" >&2
	exit 1
fi

work_dir=$(realpath "${1:?work dir}")
tag=${2:-$default_tag}
if [ "$tag" = "$default_tag" ]; then
	commit=${3:-$default_commit}
else
	commit=${3:?the commit of engine tag $tag}
fi
here=$(dirname "$(realpath "$0")")
jobs=${JOBS:-4}
mkdir -p "$work_dir"
cd "$work_dir"

# Stop unless the checkout in directory $1 is at commit $2.
verify_commit() {
	local found
	found=$(git -C "$1" rev-parse HEAD)
	if [ "$found" != "$2" ]; then
		echo "$1 is at commit $found, expected $2" >&2
		exit 1
	fi
}

# 1. toolchain: GCC 13 (as BAR's own build image), CMake, Ninja, headers; the
#    glibc 2.17 sysroot keeps the library loadable where the engine is (2.27).
#    toolchain.lock lists the packages; micromamba checks each one's SHA-256
if [ ! -x tools/env/bin/x86_64-conda-linux-gnu-g++ ]; then
	mkdir -p tools/bin
	curl -fsSL -o tools/micromamba.download \
		"https://github.com/mamba-org/micromamba-releases/releases/download/$micromamba_version/micromamba-linux-64"
	echo "$micromamba_sha256  tools/micromamba.download" | sha256sum --check --quiet
	chmod +x tools/micromamba.download
	mv tools/micromamba.download tools/bin/micromamba
	MAMBA_ROOT_PREFIX=$work_dir/tools/mamba tools/bin/micromamba create -y -q \
		-p "$work_dir/tools/env" --file "$here/toolchain.lock"
fi
export PATH=$work_dir/tools/env/bin:$PATH

# 2. sources: the engine at the tag, BARb at the engine's submodule commit.
#    The engine commit fixes the commit of every submodule
if [ ! -d recoil ]; then
	git clone -q --depth 1 --branch "$tag" https://github.com/beyond-all-reason/RecoilEngine recoil.download
	verify_commit recoil.download "$commit"
	mv recoil.download recoil
	git -C recoil submodule update -q --init --recursive --depth 1 --jobs 4 \
		AI/Skirmish/BARb rts/lib/tracy rts/lib/gflags rts/lib/entt rts/lib/cereal \
		rts/lib/RmlUi rts/lib/lunasvg rts/lib/fastgltf rts/lib/simdjson rts/lib/nowide \
		rts/lib/fmt rts/lib/mimalloc rts/lib/sse2neon rts/lib/streflop tools/pr-downloader
fi
verify_commit recoil "$commit"
if [ ! -d spring-static-libs ]; then
	git clone -q --depth 1 --branch 18.04 \
		https://github.com/beyond-all-reason/spring-static-libs.git spring-static-libs.download
	verify_commit spring-static-libs.download "$static_libs_commit"
	mv spring-static-libs.download spring-static-libs
fi
verify_commit spring-static-libs "$static_libs_commit"

# 3. our changes: the governor and the live state (new files), the engine tag
#    the library is built for, and the patches to BARb's own files
barb=recoil/AI/Skirmish/BARb
cp "$here/Budget.h" "$here/Governor.h" "$here/Governor.cpp" \
	"$here/LiveState.h" "$here/LiveState.cpp" "$barb/src/"
build_header="#define REASON8_ENGINE_TAG \"$tag\""
if [ "$(cat "$barb/src/Reason8Build.h" 2>/dev/null)" != "$build_header" ]; then
	echo "$build_header" >"$barb/src/Reason8Build.h"
fi
if ! grep -q 'reason8::UpdateGovernor' "$barb/src/AIExport.cpp"; then
	git -C "$barb" checkout -q src/AIExport.cpp
	patch -s -d "$barb" -p1 <"$here/AIExport.patch"
fi
if ! grep -q 'reason8::RegisterLiveState' "$barb/src/circuit/script/InitScript.cpp"; then
	patch -s -d "$barb" -p1 <"$here/InitScript.patch"
fi

# the command budget's own tests, with the same compiler
x86_64-conda-linux-gnu-g++ -std=c++20 -O2 -Wall -Wextra -Werror -I "$here" \
	"$here/test_budget.cpp" -o test_budget
./test_budget

# 4. configure the engine tree for the AI only, then build the one target
export PKG_CONFIG_LIBDIR=$work_dir/spring-static-libs/lib/pkgconfig:$work_dir/tools/env/lib/pkgconfig
export CMAKE_PREFIX_PATH=$work_dir/spring-static-libs:$work_dir/tools/env
export PREFER_STATIC_LIBS=TRUE
cmake -S recoil -B build -G Ninja -Wno-dev \
	-DCMAKE_BUILD_TYPE=RELWITHDEBINFO \
	-DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-O3 -g -DNDEBUG" \
	-DCMAKE_C_FLAGS_RELWITHDEBINFO="-O3 -g -DNDEBUG" \
	-DCMAKE_C_COMPILER=x86_64-conda-linux-gnu-gcc \
	-DCMAKE_CXX_COMPILER=x86_64-conda-linux-gnu-g++ \
	-DAI_TYPES=NATIVE -DAI_EXCLUDE_REGEX="^(CppTestAI|CircuitAI|NullAI.*|.*Test.*)$" \
	-DBUILD_TESTING=OFF -DBUILD_spring-legacy=OFF -DBUILD_spring-headless=OFF \
	-DBUILD_spring-dedicated=OFF >/dev/null
ninja -C build -j "$jobs" BARb

# 5. the library to install, stripped, and what it was
#    built from. The hash of our files is over "<sha256>  <name>" lines in
#    byte order of the names, as reason8.bot.library computes it
x86_64-conda-linux-gnu-strip --strip-unneeded -o libSkirmishAI.so \
	"$work_dir/build/AI/Skirmish/BARb/data/libSkirmishAI.so"
library=$work_dir/libSkirmishAI.so
sources_sha256=$(cd "$here" && find . -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort |
	xargs sha256sum -- | sha256sum | cut -d' ' -f1)
cat >reason8_library.json <<EOF
{
 "engine_tag": "$tag",
 "engine_commit": "$commit",
 "library_sha256": "$(sha256sum "$library" | cut -d' ' -f1)",
 "sources_sha256": "$sources_sha256"
}
EOF
echo "$library"
