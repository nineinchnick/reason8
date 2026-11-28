/* Tests of Choice.h, StandIn.h and ModelInputs.h without the engine. ai/native/build.sh
 * compiles and runs it before it builds the library:
 *
 *   g++ -std=c++20 -I ai/native ai/native/test_next_order.cpp -o test_next_order && ./test_next_order
 *
 * GPL-2.0-or-later. */

#include "Choice.h"
#include "ModelInputs.h"
#include "StandIn.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <set>
#include <sstream>
#include <string>

using reason8::Answers;
using reason8::Choose;
using reason8::Mask;
using reason8::Outcome;

namespace {

int failures = 0;

void Expect(bool condition, const std::string& what, int line)
{
	if (!condition) {
		std::fprintf(stderr, "test_next_order.cpp:%d: %s\n", line, what.c_str());
		++failures;
	}
}

#define EXPECT(condition) Expect((condition), #condition, __LINE__)

bool Near(float a, float b) { return std::fabs(a - b) < 1e-5f; }

bool Any(const std::string&) { return true; }

void MaskRemovesAndRescales()
{
	const Answers answers = {{"armmex", 0.2f}, {"reclaim", 0.3f}, {"armwin", 0.1f}, {"armlab", 0.f}};
	const Answers kept = Mask(answers, [](const std::string& name) { return name != "reclaim"; });
	EXPECT(kept.size() == 2);
	EXPECT(kept[0].name == "armmex" && Near(kept[0].probability, 2.f / 3.f));
	EXPECT(kept[1].name == "armwin" && Near(kept[1].probability, 1.f / 3.f));
	EXPECT(Mask(answers, [](const std::string&) { return false; }).empty());
}

void NoAnswersAndNothingPossible()
{
	EXPECT(Choose({}, Any, 0.5f).outcome == Outcome::NO_ANSWERS);
	const Answers answers = {{"assist", 1.f}};
	EXPECT(Choose(answers, [](const std::string&) { return false; }, 0.5f).outcome
		== Outcome::NOTHING_POSSIBLE);
}

void BelowThresholdNamesTheBest()
{
	Answers answers;
	for (int index = 0; index < 12; ++index) {
		answers.push_back({"unit" + std::to_string(index), index == 3 ? 1.1f : 1.f});
	}
	const reason8::Choice choice = Choose(answers, Any, 0.5f);
	EXPECT(choice.outcome == Outcome::BELOW_THRESHOLD);
	EXPECT(choice.chosen.name == "unit3");
	EXPECT(choice.candidates == 0);
}

void SamplesOnlyAboveTheThreshold()
{
	// after rescaling: a 0.5, b 0.3, c 0.15, d 0.05 (below 10%)
	const Answers answers = {{"a", 10.f}, {"b", 6.f}, {"c", 3.f}, {"d", 1.f}};
	std::map<std::string, int> drawn;
	const int draws = 9500;
	for (int index = 0; index < draws; ++index) {
		const float uniform = (index + 0.5f) / draws;
		const reason8::Choice choice = Choose(answers, Any, uniform);
		EXPECT(choice.outcome == Outcome::CHOSEN && choice.candidates == 3);
		++drawn[choice.chosen.name];
	}
	EXPECT(drawn.count("d") == 0);
	// in proportion among the candidates: 0.5, 0.3 and 0.15 of 0.95
	EXPECT(std::abs(drawn["a"] - 5000) <= 1);
	EXPECT(std::abs(drawn["b"] - 3000) <= 1);
	EXPECT(std::abs(drawn["c"] - 1500) <= 1);
	// the ends of the range stay inside it
	EXPECT(Choose(answers, Any, 0.f).chosen.name == "a");
	EXPECT(Choose(answers, Any, 0.99999f).chosen.name == "c");
	EXPECT(Choose(answers, Any, 1.f).chosen.name == "c");
}

void TheMaskComesBeforeTheThreshold()
{
	// 0.09 is below the threshold, but becomes 0.18 once "assist" is removed
	const Answers answers = {{"assist", 0.5f}, {"armmex", 0.41f}, {"armwin", 0.09f}};
	int wind = 0;
	for (int index = 0; index < 100; ++index) {
		const reason8::Choice choice = Choose(answers, [](const std::string& name) { return name != "assist"; },
			(index + 0.5f) / 100);
		EXPECT(choice.candidates == 2);
		wind += choice.chosen.name == "armwin";
	}
	EXPECT(wind == 18);
}

void JobsAreKnown()
{
	EXPECT(reason8::IsJob("assist") && reason8::IsJob("resurrect"));
	EXPECT(!reason8::IsJob("armmex"));
}

void StandInReadsItsTable()
{
	std::istringstream text(
		"# a comment\n"
		"armcom 0 armmex 0.5 armwin 0.3\n"
		"armcom 2 armwin 0.6 assist 0.4\n"
		"broken\n"
		"armlab 1 armck 1\n");
	reason8::StandInModel model;
	EXPECT(model.Load(text) == 3);
	EXPECT(model.Units() == 2);
	reason8::IdleBuilder builder;
	builder.unit = "armcom";
	builder.frame = 0;
	EXPECT(model.Predict(builder).size() == 2 && model.Predict(builder)[0].name == "armmex");
	builder.frame = 1 * 1800 + 5;  // minute 1: still the row of minute 0
	EXPECT(model.Predict(builder)[0].name == "armmex");
	builder.frame = 20 * 1800;  // past the last row: the last
	EXPECT(model.Predict(builder)[0].name == "armwin" && Near(model.Predict(builder)[1].probability, 0.4f));
	builder.unit = "armlab";
	builder.frame = 0;  // before the first row: the first
	EXPECT(model.Predict(builder).size() == 1);
	builder.unit = "armck";
	EXPECT(model.Predict(builder).empty());
}

double NumberOf(const reason8::Inputs& inputs, const std::string& name)
{
	const double* value = inputs.Number(name);
	return value == nullptr ? -1.0 : *value;
}

std::string NameOf(const reason8::Inputs& inputs, const std::string& name)
{
	const std::string* value = inputs.Name(name);
	return value == nullptr ? "(missing)" : *value;
}

void HistoryCountsStepsAndOrders()
{
	const std::set<std::string> types = {"mex", "win", "com", "other"};
	reason8::OrderHistory history;
	reason8::Inputs first;
	history.Fill(first, 7, types);
	EXPECT(NumberOf(first, "step_idx") == 0 && NumberOf(first, "decision_index") == 0);
	EXPECT(NameOf(first, "previous_1") == "<start>" && NameOf(first, "builder_previous") == "<start>");
	EXPECT(NumberOf(first, "ordered_mex") == 0 && NumberOf(first, "ordered_assist") == 0);

	history.Record(7, "armmex", 10);
	history.Record(8, "armmex", 16);  // 6 frames later: the same step
	history.Record(8, "armmex", 23);  // 7 frames later: a new step
	history.Record(7, "assist", 23);
	history.Record(9, "armlab", 23);  // a type not listed: other
	reason8::Inputs inputs;
	history.Fill(inputs, 8, types);
	EXPECT(NumberOf(inputs, "step_idx") == 4);
	EXPECT(NumberOf(inputs, "decision_index") == 5);
	EXPECT(NameOf(inputs, "previous_1") == "armlab");
	EXPECT(NameOf(inputs, "builder_previous") == "armmex");
	EXPECT(NumberOf(inputs, "ordered_mex") == 3);
	EXPECT(NumberOf(inputs, "ordered_other") == 1);
	EXPECT(NumberOf(inputs, "ordered_win") == 0);
	EXPECT(NumberOf(inputs, "ordered_assist") == 1);
	reason8::Inputs other;
	history.Fill(other, 7, types);
	EXPECT(NameOf(other, "builder_previous") == "assist");
}

void HistoryChainsRuns()
{
	// each order is compared with the one directly before it, so a run chains
	reason8::OrderHistory history;
	for (int frame = 0; frame <= 30; frame += 5) {
		history.Record(1, "armwin", frame);
	}
	EXPECT(history.Steps() == 1 && history.Orders() == 7);
}

void TypesAndFactions()
{
	const std::set<std::string> types = {"lab", "com", "other"};
	EXPECT(reason8::UnitType("corlab") == "lab" && reason8::UnitType("legcom") == "com");
	EXPECT(reason8::UnitType("dbg_sphere") == "dbg_sphere");
	EXPECT(reason8::TypeOf("armlab", types) == "lab" && reason8::TypeOf("armvp", types) == "other");
	EXPECT(reason8::FactionOf("legcom") == "Legion" && reason8::FactionOf("armcom") == "Armada");
	EXPECT(reason8::FactionOf("xyz").empty());
}

void RoundedAsTheExportWrites()
{
	EXPECT(reason8::ExportRounded(533.997, -1) == 533.0);  // "%d" cuts
	EXPECT(reason8::ExportRounded(2.04, 1) == 2.0);
	EXPECT(reason8::ExportRounded(2.06, 1) == 2.1);
	EXPECT(reason8::ExportRounded(30.5, 0) == 30.0);  // printf rounds half to even
	EXPECT(reason8::ExportRounded(38.0055, 0) == 38.0);
}

}  // namespace

int main()
{
	MaskRemovesAndRescales();
	NoAnswersAndNothingPossible();
	BelowThresholdNamesTheBest();
	SamplesOnlyAboveTheThreshold();
	TheMaskComesBeforeTheThreshold();
	JobsAreKnown();
	StandInReadsItsTable();
	HistoryCountsStepsAndOrders();
	HistoryChainsRuns();
	TypesAndFactions();
	RoundedAsTheExportWrites();
	if (failures != 0) {
		std::fprintf(stderr, "%d failed\n", failures);
		return EXIT_FAILURE;
	}
	std::printf("test_next_order: all passed\n");
	return EXIT_SUCCESS;
}
