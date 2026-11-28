/* Reason8 builder model inputs: the parts that need no engine. The library
 * computes every input of the builder model as the decision table defines it
 * (docs/reference/builder-model.md, "The inputs"); this file holds the rules
 * that are plain bookkeeping, so that test_next_order.cpp can test them: the
 * order history, the unit types, and the rounding of the state export.
 * GPL-2.0-or-later. */

#ifndef REASON8_MODEL_INPUTS_H
#define REASON8_MODEL_INPUTS_H

#include "Choice.h"
#include "Model.h"

#include <cstdio>
#include <cstdlib>
#include <map>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace reason8 {

/* The answer before the first, as the table names it (reason8.models.ngram.START). */
inline const char* const START_ANSWER = "<start>";
/* The type of the units of no listed type (reason8.context.table.OTHER). */
inline const char* const OTHER_TYPE = "other";
/* An order this many frames or fewer after an order of the same answer is part of its
 * step (reason8.openings.dataset.STEP_FRAMES, ADR 0013). */
constexpr int STEP_FRAMES = 6;

/* A unit name without its faction prefix: armlab and corlab are both lab
 * (reason8.openings.extract.unit_role). */
inline std::string UnitType(const std::string& unit)
{
	const std::string prefix = unit.substr(0, 3);
	return prefix == "arm" || prefix == "cor" || prefix == "leg" ? unit.substr(3) : unit;
}

/* The type of a unit among `types`, OTHER_TYPE when it is none of them
 * (reason8.context.table.role_expression). */
inline std::string TypeOf(const std::string& unit, const std::set<std::string>& types)
{
	const std::string type = UnitType(unit);
	return types.count(type) > 0 ? type : OTHER_TYPE;
}

/* The faction of a unit, by its name's prefix; "" for none. */
inline std::string FactionOf(const std::string& unit)
{
	const std::string prefix = unit.substr(0, 3);
	if (prefix == "arm") return "Armada";
	if (prefix == "cor") return "Cortex";
	if (prefix == "leg") return "Legion";
	return "";
}

/* A value as the state export writes it (reason8_state_export.lua): with
 * `decimals` digits after the point, as Lua's string.format("%.<n>f") rounds,
 * or with decimals < 0 as "%d" writes a number: cut to a whole number. */
inline double ExportRounded(double value, int decimals)
{
	if (decimals < 0) {
		return static_cast<double>(static_cast<long long>(value));
	}
	char text[64];
	std::snprintf(text, sizeof(text), "%.*f", decimals, value);
	return std::strtod(text, nullptr);
}

/* The team's economy as the table has it: the eight values of a resource line
 * of the state export, rounded as it writes them. */
struct Economy {
	static constexpr int SIZE = 8;
	static const char* const* Names()
	{
		static const char* const names[SIZE] = {"metal", "metal_storage", "metal_income", "metal_expense",
			"energy", "energy_storage", "energy_income", "energy_expense"};
		return names;
	}
	/* Decimals of each value in the export ("%d,%d,%.1f,%.1f,%d,%d,%.0f,%.0f"). */
	static const int* Decimals()
	{
		static const int decimals[SIZE] = {-1, -1, 1, 1, -1, -1, 0, 0};
		return decimals;
	}

	int frame = -1;  // -1: not read yet
	double values[SIZE] = {};
};

/* The team's earlier orders, the model's and BARb's, for the order history of
 * the next decision. Each order counts once (a decision of the bot is one
 * order; a player's drag counts each building); a run of orders of one answer
 * at most STEP_FRAMES apart is one step. */
class OrderHistory {
public:
	void Record(int unitId, const std::string& answer, int frame)
	{
		const bool continues = answer == lastAnswer && frame - lastFrame <= STEP_FRAMES;
		if (!continues) {
			++steps;
			previousStep = answer;
		}
		lastAnswer = answer;
		lastFrame = frame;
		++orders;
		++byAnswer[answer];
		builderPrevious[unitId] = answer;
	}

	int Orders() const { return orders; }
	int Steps() const { return steps; }

	/* The history inputs of the next decision, for the builder `unitId`:
	 * step_idx, decision_index, previous_1, builder_previous, and
	 * ordered_<type> for each of `types` and each job. */
	void Fill(Inputs& inputs, int unitId, const std::set<std::string>& types) const
	{
		inputs.Set("step_idx", steps);
		inputs.Set("decision_index", orders);
		inputs.Set("previous_1", previousStep);
		const auto previous = builderPrevious.find(unitId);
		inputs.Set("builder_previous", previous == builderPrevious.end() ? START_ANSWER : previous->second);
		std::map<std::string, int> ordered;
		for (const std::string& type : types) {
			ordered[type] = 0;
		}
		for (const std::string& job : Jobs()) {
			ordered[job] = 0;
		}
		for (const auto& [answer, count] : byAnswer) {
			ordered[IsJob(answer) ? answer : TypeOf(answer, types)] += count;
		}
		for (const auto& [name, count] : ordered) {
			inputs.Set("ordered_" + name, count);
		}
	}

private:
	int orders = 0;
	int steps = 0;
	std::string lastAnswer;
	int lastFrame = -1000;
	std::string previousStep = START_ANSWER;
	std::map<std::string, int> byAnswer;
	std::unordered_map<int, std::string> builderPrevious;
};

}  // namespace reason8

#endif  // REASON8_MODEL_INPUTS_H
