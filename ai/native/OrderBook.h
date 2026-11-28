/* Reason8 order book: what became of the model's orders for idle builders
 * (ADR 0019), without the engine. GPL-2.0-or-later.
 *
 * An order the model chose is carried out once its task has lasted
 * CARRIED_OUT_FRAMES, or once the builder is idle again after a task that
 * did not end at once (a short build it finished): only then does it enter
 * the model's order history. An order that cannot be given, or whose task
 * ends at once, was not carried out: it never enters the history, and the
 * same answer is held back for that builder for COOL_DOWN_FRAMES, so that
 * the model does not choose it again and again while nothing changed. */

#ifndef REASON8_ORDER_BOOK_H
#define REASON8_ORDER_BOOK_H

#include "Choice.h"

#include <algorithm>

#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace reason8 {

/* One second of game time: an order whose task lasts less than this ended at
 * once. A builder idle again within a second was given nothing to do. */
constexpr int CARRIED_OUT_FRAMES = 30;

/* After an order could not be carried out, the same answer is held back for
 * the same builder for this long: 30 s of game time, long enough to stop the
 * loops of a builder given the same order again and again, short against an
 * opening of minutes. */
constexpr int COOL_DOWN_FRAMES = 30 * 30;

/* Whether an order's task that ended after `lastedFrames` was not carried
 * out. A task that ended unfinished within a second did nothing; a job that
 * ended done within a second had nothing to do (no feature to reclaim, no one
 * to repair). A build done within a second was finished: carried out. */
inline bool EndedAtOnce(const std::string& answer, bool done, int lastedFrames)
{
	return lastedFrames < CARRIED_OUT_FRAMES && (!done || IsJob(answer));
}

class OrderBook {
public:
	struct Order {
		int unitId = -1;
		std::string answer;
		int frame = 0;  // when it was chosen
	};

	/* The model chose `answer` for the builder at `frame`. An order of the
	 * same builder still pending is returned: its builder is deciding again
	 * without its task having ended at once, so it was carried out. */
	std::optional<Order> Chosen(int unitId, const std::string& answer, int frame)
	{
		std::optional<Order> previous = TakePending(unitId);
		pending[unitId] = {unitId, answer, frame};
		return previous;
	}

	/* The builder's pending order, if any, removed from the book. */
	std::optional<Order> TakePending(int unitId)
	{
		const auto found = pending.find(unitId);
		if (found == pending.end()) {
			return std::nullopt;
		}
		Order order = found->second;
		pending.erase(found);
		return order;
	}

	/* The pending orders whose task has lasted CARRIED_OUT_FRAMES by `frame`,
	 * removed from the book: they were carried out. Oldest first. */
	std::vector<Order> Due(int frame)
	{
		std::vector<Order> due;
		for (auto order = pending.begin(); order != pending.end();) {
			if (frame - order->second.frame >= CARRIED_OUT_FRAMES) {
				due.push_back(order->second);
				order = pending.erase(order);
			} else {
				++order;
			}
		}
		std::sort(due.begin(), due.end(), [](const Order& a, const Order& b) {
			return a.frame != b.frame ? a.frame < b.frame : a.unitId < b.unitId;
		});
		return due;
	}

	/* The builder's order `answer` could not be carried out at `frame`: it is
	 * held back for the builder, and dropped if it is still pending. Returns
	 * whether it was pending (never entered the history). */
	bool Failed(int unitId, const std::string& answer, int frame)
	{
		heldBack[unitId][answer] = frame + COOL_DOWN_FRAMES;
		const auto found = pending.find(unitId);
		if (found == pending.end() || found->second.answer != answer) {
			return false;
		}
		pending.erase(found);
		return true;
	}

	/* Whether `answer` is held back for the builder at `frame`. */
	bool HeldBack(int unitId, const std::string& answer, int frame) const
	{
		const auto unit = heldBack.find(unitId);
		if (unit == heldBack.end()) {
			return false;
		}
		const auto until = unit->second.find(answer);
		return until != unit->second.end() && frame < until->second;
	}

	/* The answers held back for the builder at `frame`, by name. */
	std::vector<std::string> HeldBackAnswers(int unitId, int frame) const
	{
		std::vector<std::string> answers;
		const auto unit = heldBack.find(unitId);
		if (unit != heldBack.end()) {
			for (const auto& [answer, until] : unit->second) {
				if (frame < until) {
					answers.push_back(answer);
				}
			}
		}
		return answers;
	}

private:
	std::map<int, Order> pending;  // by builder: chosen, given, not yet carried out
	std::unordered_map<int, std::map<std::string, int>> heldBack;  // builder -> answer -> until frame
};

}  // namespace reason8

#endif  // REASON8_ORDER_BOOK_H
