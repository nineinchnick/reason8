/* Tests of Trees.h against the test vectors of the builder model
 * (tests/models/builder_vectors.json, docs/reference/builder-model.md):
 * every decision's encoded row, the probability of every answer, the
 * possible answers after the mask and the answer drawn. ai/native/build.sh
 * compiles and runs it before it builds the library, with BARb's jsoncpp:
 *
 *   g++ -std=c++20 -I ai/native -I <BARb>/src/lib ai/native/test_trees.cpp \
 *       <BARb>/src/lib/json/jsoncpp.cpp -o test_trees
 *   ./test_trees tests/models/builder_vectors.json
 *
 * Vectors written for a trained model (`reason8 model vectors --model`) name
 * its file instead of holding it; it is read from the vectors' folder, and
 * the test then reports what loading and deciding take.
 *
 * GPL-2.0-or-later. */

#include "Choice.h"
#include "Trees.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <set>
#include <string>
#include <vector>

#ifdef __linux__
#include <unistd.h>
#endif

using reason8::Answers;
using reason8::Inputs;
using reason8::TreeModel;

namespace {

int failures = 0;

void Fail(const std::string& what)
{
	if (failures < 20) {
		std::fprintf(stderr, "test_trees: %s\n", what.c_str());
	}
	++failures;
}

/* The resident memory of the process in bytes, 0 where it is not known. */
std::size_t ResidentBytes()
{
#ifdef __linux__
	std::ifstream statm("/proc/self/statm");
	std::size_t pages = 0, resident = 0;
	statm >> pages >> resident;
	return resident * static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
#else
	return 0;
#endif
}

double Seconds(std::chrono::steady_clock::time_point since)
{
	return std::chrono::duration<double>(std::chrono::steady_clock::now() - since).count();
}

Inputs ReadInputs(const Json::Value& values)
{
	Inputs inputs;
	for (const std::string& name : values.getMemberNames()) {
		const Json::Value& value = values[name];
		if (value.isString()) {
			inputs.Set(name, value.asString());
		} else if (value.isBool()) {
			inputs.Set(name, value.asBool() ? 1.0 : 0.0);
		} else if (value.isNumeric()) {
			inputs.Set(name, value.asDouble());
		}  // null: missing
	}
	return inputs;
}

void Check(const TreeModel& model, const Json::Value& decision, int number, double tolerance)
{
	const std::string where = "decision " + std::to_string(number) + ": ";
	const std::vector<float> row = model.Encode(ReadInputs(decision["inputs"]));
	const Json::Value& encoded = decision["encoded"];
	if (encoded.size() != row.size()) {
		Fail(where + "the row has " + std::to_string(row.size()) + " inputs, expected " + std::to_string(encoded.size()));
		return;
	}
	for (Json::ArrayIndex index = 0; index < encoded.size(); ++index) {
		const bool expectMissing = encoded[index].isNull();
		const bool same = expectMissing ? std::isnan(row[index])
		                                : row[index] == static_cast<float>(encoded[index].asDouble());
		if (!same) {
			Fail(where + "input " + model.Features()[index].name + " encoded " + std::to_string(row[index]));
		}
	}

	const Answers answers = model.Predict(row);
	const Json::Value& probabilities = decision["probabilities"];
	if (probabilities.size() != answers.size()) {
		Fail(where + "the model gives " + std::to_string(answers.size()) + " answers, expected "
			+ std::to_string(probabilities.size()));
		return;
	}
	for (Json::ArrayIndex index = 0; index < probabilities.size(); ++index) {
		if (std::fabs(answers[index].probability - probabilities[index].asDouble()) > tolerance) {
			Fail(where + answers[index].name + " has probability " + std::to_string(answers[index].probability)
				+ ", expected " + std::to_string(probabilities[index].asDouble()));
		}
	}

	std::set<std::string> canGive;
	for (const Json::Value& answer : decision["can_give"]) {
		canGive.insert(answer.asString());
	}
	const reason8::Choice choice = reason8::Choose(answers,
		[&](const std::string& answer) { return canGive.count(answer) > 0; },
		static_cast<float>(decision["uniform"].asDouble()), model.Threshold());
	const Json::Value& possible = decision["possible"];
	if (possible.size() != choice.possible.size()) {
		Fail(where + std::to_string(choice.possible.size()) + " possible answers, expected "
			+ std::to_string(possible.size()));
		return;
	}
	for (Json::ArrayIndex index = 0; index < possible.size(); ++index) {
		if (choice.possible[index].name != possible[index][0].asString()
				|| std::fabs(choice.possible[index].probability - possible[index][1].asDouble()) > tolerance) {
			Fail(where + "possible answer " + std::to_string(index) + " is " + choice.possible[index].name + " "
				+ std::to_string(choice.possible[index].probability) + ", expected " + possible[index][0].asString());
		}
	}
	const std::string drawn = choice.outcome == reason8::Outcome::CHOSEN ? choice.chosen.name : "";
	const std::string expected = decision["answer"].isNull() ? "" : decision["answer"].asString();
	if (drawn != expected) {
		Fail(where + "drew '" + drawn + "', expected '" + expected + "'");
	}
}

}  // namespace

int main(int argc, char** argv)
{
	if (argc != 2) {
		std::fprintf(stderr, "usage: test_trees <vectors.json>\n");
		return EXIT_FAILURE;
	}
	const std::string vectorsPath = argv[1];
	std::ifstream file(vectorsPath, std::ios::binary);
	Json::CharReaderBuilder builder;
	Json::Value vectors;
	std::string errors;
	if (!Json::parseFromStream(builder, file, &vectors, &errors)) {
		std::fprintf(stderr, "test_trees: cannot read %s: %s\n", vectorsPath.c_str(), errors.c_str());
		return EXIT_FAILURE;
	}

	std::string error;
	std::shared_ptr<const TreeModel> model;
	const bool external = vectors.isMember("model_file");
	if (external) {
		const std::size_t slash = vectorsPath.find_last_of("/\\");
		const std::string folder = slash == std::string::npos ? "." : vectorsPath.substr(0, slash);
		const std::string path = folder + "/" + vectors["model_file"].asString();
		const std::size_t before = ResidentBytes();
		const auto start = std::chrono::steady_clock::now();
		bool loaded = false;
		model = TreeModel::Shared(path, error, loaded);
		const double seconds = Seconds(start);
		if (model) {
			bool again = true;
			const std::shared_ptr<const TreeModel> second = TreeModel::Shared(path, error, again);
			if (!loaded || again || second != model) {
				Fail("a second AI of the process does not share the loaded model");
			}
			std::printf("test_trees: %s: %zu trees, %zu nodes, %zu classes, %zu inputs; loaded in %.2f s, "
				"arrays %.1f MB, resident memory %.1f MB more after loading\n",
				model->Name().c_str(), model->Trees(), model->Nodes(), model->Classes(), model->Features().size(),
				seconds, model->Bytes() / 1e6, (ResidentBytes() - before) / 1e6);
		}
	} else {
		// the vectors hold the model: read it as parsed, and from a file as the game does
		model = TreeModel::FromJson(vectors["model"], error);
		const std::string path = "test_trees_model.json";
		{
			std::ofstream copy(path, std::ios::binary);
			copy << Json::writeString(Json::StreamWriterBuilder(), vectors["model"]);
		}
		const std::shared_ptr<const TreeModel> loaded = TreeModel::Load(path, error);
		std::remove(path.c_str());
		if (!model || !loaded) {
			std::fprintf(stderr, "test_trees: %s\n", error.c_str());
			return EXIT_FAILURE;
		}
		if (loaded->Nodes() != model->Nodes() || loaded->Trees() != model->Trees() || loaded->Bytes() != model->Bytes()) {
			Fail("the model read from a file differs from the one parsed whole");
		}
		for (const Json::Value& decision : vectors["decisions"]) {
			const std::vector<float> row = model->Encode(ReadInputs(decision["inputs"]));
			const Answers whole = model->Predict(row), read = loaded->Predict(row);
			for (std::size_t index = 0; index < whole.size(); ++index) {
				if (whole[index].probability != read[index].probability) {
					Fail("the model read from a file decides otherwise than the one parsed whole");
					break;
				}
			}
		}
	}
	if (!model) {
		std::fprintf(stderr, "test_trees: %s\n", error.c_str());
		return EXIT_FAILURE;
	}

	const double tolerance = vectors["tolerance"].asDouble();
	const Json::Value& decisions = vectors["decisions"];
	const auto start = std::chrono::steady_clock::now();
	int number = 0;
	for (const Json::Value& decision : decisions) {
		Check(*model, decision, number++, tolerance);
	}
	const double seconds = Seconds(start);
	if (external && number > 0) {
		std::vector<float> row = model->Encode(ReadInputs(decisions[0]["inputs"]));
		const int repeats = 200;
		const auto timed = std::chrono::steady_clock::now();
		float sink = 0.f;
		for (int repeat = 0; repeat < repeats; ++repeat) {
			sink += model->Predict(row)[0].probability;
		}
		std::printf("test_trees: %.3f ms per decision (%d checked in %.2f s)%s\n",
			Seconds(timed) / repeats * 1e3, number, seconds, sink < 0.f ? " " : "");
	}
	if (failures != 0) {
		std::fprintf(stderr, "test_trees: %d of the checks of %d decisions failed\n", failures, number);
		return EXIT_FAILURE;
	}
	std::printf("test_trees: all %d decisions of %s reproduced\n", number, model->Name().c_str());
	return EXIT_SUCCESS;
}
