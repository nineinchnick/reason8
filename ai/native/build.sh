#!/usr/bin/env bash
# Build BARb (CircuitAI) from source with the Reason8 command governor, the
# live state and the next orders, without root, for Linux x86-64 or Windows
# x86-64, from the engine source at the tag of the engine the library will
# run in. See docs/reference/in-game.md, "Our own build of BARb's library".
# `reason8 bot build` runs it.
#
#   ai/native/build.sh [--platform linux|windows] <work dir> [engine tag] [engine commit]
#
# Linux (the default) builds with a conda-forge GCC 13 toolchain and BAR's
# prebuilt static libraries. Windows cross-compiles in BAR's own build image,
# the one the engine's release builds the Windows engine in, run by podman
# (or docker) without network.
#
# Leaves the library, stripped, at <work dir>/libSkirmishAI.so (Linux) or
# <work dir>/SkirmishAI.dll (Windows), and <work dir>/reason8_library.json,
# which says what it was built from: the platform, the engine tag and commit,
# and the SHA-256 of the library and of the files in ai/native.
#
# Everything downloaded is checked before it runs: micromamba and the
# toolchain packages against the SHA-256 recorded here and in toolchain.lock,
# the build image against the digest recorded here, the sources against the
# commits recorded here. A different engine tag needs its commit as the third
# argument; for Windows, check that windows_image is still the one that
# engine's release used.
set -euo pipefail

micromamba_version=2.10.0-0
micromamba_sha256=701f39c06f8e6a670a0e186c8479b9e5c0502a2f0cda6cef65d83bdd2875e8bd
default_tag=2026.09.03
default_commit=8688dcc2690a8db4e6624dd516ef5da8cf3c5ec8
static_libs_commit=25a1f8685b3e60fc09aa111a70a1f6a8c89c8154
# image_version[amd64-windows] of docker-build-v2/images_versions.sh in the
# engine at default_tag: the image its release built the Windows engine in
windows_image=ghcr.io/beyond-all-reason/recoil-build-amd64-windows@sha256:3ba630ac0c181a95dde522c3a4a81df2302914c7c4e6674e6bde0d4f6bf058ef

platform=linux
if [ "${1:-}" = --platform ]; then
	platform=${2:?--platform linux or windows}
	shift 2
fi
case $platform in
linux) library_name=libSkirmishAI.so ;;
windows) library_name=SkirmishAI.dll ;;
*)
	echo "unknown platform $platform: linux or windows" >&2
	exit 1
	;;
esac

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

# 1. toolchain. Linux: GCC 13 (as BAR's own build image), CMake, Ninja,
#    headers; the glibc 2.17 sysroot keeps the library loadable where the
#    engine is (2.27). toolchain.lock lists the packages; micromamba checks
#    each one's SHA-256. Windows: the build image, with MinGW GCC 13, CMake,
#    Ninja and BAR's Windows libraries (mingwlibs64) inside; the container
#    runtime checks it against the digest when it pulls it
if [ "$platform" = windows ]; then
	if command -v podman >/dev/null; then
		# rootless podman: keep our user id inside, so the files stay ours
		container=(podman run --userns=keep-id)
	elif command -v docker >/dev/null; then
		container=(docker run)
	else
		echo "the Windows build needs podman or docker" >&2
		exit 1
	fi
	container+=(--rm --network=none --user "$(id -u):$(id -g)"
	-v "$work_dir:$work_dir:z" -v "$here:$here:ro,z" -w "$work_dir"
	-e CCACHE_DISABLE=1 -e JOBS="$jobs" "$windows_image")
elif [ ! -x tools/env/bin/x86_64-conda-linux-gnu-g++ ]; then
	mkdir -p tools/bin
	curl -fsSL -o tools/micromamba.download \
		"https://github.com/mamba-org/micromamba-releases/releases/download/$micromamba_version/micromamba-linux-64"
	echo "$micromamba_sha256  tools/micromamba.download" | sha256sum --check --quiet
	chmod +x tools/micromamba.download
	mv tools/micromamba.download tools/bin/micromamba
	MAMBA_ROOT_PREFIX=$work_dir/tools/mamba tools/bin/micromamba create -y -q \
		-p "$work_dir/tools/env" --file "$here/toolchain.lock"
fi
if [ "$platform" = linux ]; then
	export PATH=$work_dir/tools/env/bin:$PATH
fi

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
if [ "$platform" = linux ]; then
	if [ ! -d spring-static-libs ]; then
		git clone -q --depth 1 --branch 18.04 \
			https://github.com/beyond-all-reason/spring-static-libs.git spring-static-libs.download
		verify_commit spring-static-libs.download "$static_libs_commit"
		mv spring-static-libs.download spring-static-libs
	fi
	verify_commit spring-static-libs "$static_libs_commit"
fi

# 3. our changes: the governor, the live state and the next orders (new
#    files), the engine tag the library is built for, and the patches to
#    BARb's own files
barb=recoil/AI/Skirmish/BARb
cp "$here/Budget.h" "$here/Governor.h" "$here/Governor.cpp" \
	"$here/LiveState.h" "$here/LiveState.cpp" "$here/Choice.h" "$here/Model.h" \
	"$here/StandIn.h" "$here/Trees.h" "$here/NextOrder.h" "$here/NextOrder.cpp" "$barb/src/"
build_header="#define REASON8_ENGINE_TAG \"$tag\""
if [ "$(cat "$barb/src/Reason8Build.h" 2>/dev/null)" != "$build_header" ]; then
	echo "$build_header" >"$barb/src/Reason8Build.h"
fi
if ! grep -q 'reason8::UnitDamaged' "$barb/src/AIExport.cpp"; then
	git -C "$barb" checkout -q src/AIExport.cpp
	patch -s -d "$barb" -p1 <"$here/AIExport.patch"
fi
if ! grep -q 'reason8::RegisterNextOrder' "$barb/src/circuit/script/InitScript.cpp"; then
	git -C "$barb" checkout -q src/circuit/script/InitScript.cpp
	patch -s -d "$barb" -p1 <"$here/InitScript.patch"
fi

# 4. the tests of the command budget, of the choice and of the trees, with
#    the same compiler (the trees' test with BARb's jsoncpp, against the
#    builder model's test vectors); then the engine tree configured for the
#    AI only, the one target built and stripped
cmake_options=(-G Ninja -Wno-dev
	-DCMAKE_BUILD_TYPE=RELWITHDEBINFO
	"-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O3 -g -DNDEBUG"
	"-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O3 -g -DNDEBUG"
	-DAI_TYPES=NATIVE "-DAI_EXCLUDE_REGEX=^(CppTestAI|CircuitAI|NullAI.*|.*Test.*)$"
	-DBUILD_TESTING=OFF -DBUILD_spring-legacy=OFF -DBUILD_spring-headless=OFF
	-DBUILD_spring-dedicated=OFF)
test_options=(-std=c++20 -O2 -Wall -Wextra -Werror -I "$here")
tests=(test_budget test_next_order)
vectors=$(realpath "$here/../../tests/models/builder_vectors.json")
json_lib=$barb/src/lib
if [ "$platform" = linux ]; then
	for test in "${tests[@]}"; do
		x86_64-conda-linux-gnu-g++ "${test_options[@]}" "$here/$test.cpp" -o "$test"
		"./$test"
	done
	x86_64-conda-linux-gnu-g++ -std=c++20 -O2 -I "$json_lib" -c "$json_lib/json/jsoncpp.cpp" -o jsoncpp.o
	x86_64-conda-linux-gnu-g++ "${test_options[@]}" -I "$json_lib" "$here/test_trees.cpp" jsoncpp.o \
		-o test_trees
	./test_trees "$vectors"

	export PKG_CONFIG_LIBDIR=$work_dir/spring-static-libs/lib/pkgconfig:$work_dir/tools/env/lib/pkgconfig
	export CMAKE_PREFIX_PATH=$work_dir/spring-static-libs:$work_dir/tools/env
	export PREFER_STATIC_LIBS=TRUE
	cmake -S recoil -B build "${cmake_options[@]}" \
		-DCMAKE_C_COMPILER=x86_64-conda-linux-gnu-gcc \
		-DCMAKE_CXX_COMPILER=x86_64-conda-linux-gnu-g++ >/dev/null
	ninja -C build -j "$jobs" BARb
	x86_64-conda-linux-gnu-strip --strip-unneeded -o "$library_name" \
		"build/AI/Skirmish/BARb/data/$library_name"
else
	# the image cannot run what it builds: the test runs where Windows
	# programs do (WSL), and is compiled everywhere
	for test in "${tests[@]}"; do
		"${container[@]}" x86_64-w64-mingw32-g++-posix "${test_options[@]}" "$here/$test.cpp" \
			-static -o "$test.exe"
	done
	"${container[@]}" x86_64-w64-mingw32-g++-posix -std=c++20 -O2 -I "$json_lib" \
		-c "$json_lib/json/jsoncpp.cpp" -o jsoncpp.o
	"${container[@]}" x86_64-w64-mingw32-g++-posix "${test_options[@]}" -I "$json_lib" \
		"$here/test_trees.cpp" jsoncpp.o -static -o test_trees.exe
	if [ -e /proc/sys/fs/binfmt_misc/WSLInterop ]; then
		for test in "${tests[@]}"; do
			"./$test.exe"
		done
		./test_trees.exe "$(wslpath -w "$vectors")"
	else
		echo "the tests' .exe built but not run: this system runs no Windows programs" >&2
	fi

	# the image's CMAKE_TOOLCHAIN_FILE picks MinGW, its MINGWLIBS the libraries
	# shellcheck disable=SC2016 # expanded in the container
	"${container[@]}" bash -c 'set -e
		cmake -S recoil -B build "$@" >/dev/null
		ninja -C build -j "$JOBS" BARb
		x86_64-w64-mingw32-strip --strip-unneeded -o SkirmishAI.dll \
			build/AI/Skirmish/BARb/data/SkirmishAI.dll' -- "${cmake_options[@]}"
fi

# 5. what the library was built from. The hash of our files is over
#    "<sha256>  <name>" lines in byte order of the names, as
#    reason8.bot.library computes it
library=$work_dir/$library_name
sources_sha256=$(cd "$here" && find . -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort |
	xargs sha256sum -- | sha256sum | cut -d' ' -f1)
cat >reason8_library.json <<EOF
{
 "platform": "$platform",
 "library": "$library_name",
 "engine_tag": "$tag",
 "engine_commit": "$commit",
 "library_sha256": "$(sha256sum "$library" | cut -d' ' -f1)",
 "sources_sha256": "$sources_sha256"
}
EOF
echo "$library"
