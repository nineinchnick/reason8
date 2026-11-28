/* Reason8 stand-in model. GPL-2.0-or-later.
 *
 * NOT THE LEARNED MODEL. A fixed table that answers for each kind of builder
 * (by unit name) and minute of the game with how often players' builders of
 * that unit got each answer in that minute, measured on the decision table by
 * `reason8 bot export-next-order`. It knows nothing of the game state. It
 * stands in for the trees of ADR 0019 so that the next orders, the mask and
 * the choice can be played and checked before the learned model is in.
 *
 * The table is text, one row per builder unit and minute:
 *
 *   <builder unit> <minute> <answer> <probability> <answer> <probability> ...
 *
 * Lines starting with '#' are comments. A minute past the last row of a unit
 * takes that unit's last row. */

#ifndef REASON8_STAND_IN_H
#define REASON8_STAND_IN_H

#include "Model.h"

#include <istream>
#include <iterator>
#include <map>
#include <sstream>
#include <string>
#include <utility>

namespace reason8 {

class StandInModel final : public AnswerModel {
public:
	/* Reads the table; returns the rows read. Rows that do not parse are skipped. */
	int Load(std::istream& text)
	{
		int rows = 0;
		std::string line;
		while (std::getline(text, line)) {
			if (line.empty() || line[0] == '#') {
				continue;
			}
			std::istringstream fields(line);
			std::string unit;
			int minute = -1;
			if (!(fields >> unit >> minute) || minute < 0) {
				continue;
			}
			Answers answers;
			std::string name;
			float probability;
			while (fields >> name >> probability) {
				answers.push_back({name, probability});
			}
			if (answers.empty()) {
				continue;
			}
			table[unit][minute] = std::move(answers);
			++rows;
		}
		return rows;
	}

	std::string Name() const override { return "stand-in"; }

	Answers Predict(const IdleBuilder& builder) override
	{
		const auto unit = table.find(builder.unit);
		if (unit == table.end() || unit->second.empty()) {
			return {};
		}
		const int minute = builder.frame / FRAMES_PER_MINUTE;
		auto row = unit->second.upper_bound(minute);  // the first row after the minute
		if (row == unit->second.begin()) {
			return row->second;  // before the first row: the first
		}
		return std::prev(row)->second;
	}

	std::size_t Units() const { return table.size(); }

private:
	static constexpr int FRAMES_PER_MINUTE = 30 * 60;
	std::map<std::string, std::map<int, Answers>> table;  // unit -> minute -> answers
};

}  // namespace reason8

#endif  // REASON8_STAND_IN_H
