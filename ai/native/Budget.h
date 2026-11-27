/* Reason8 command budget: counts a team's unit commands as actions, the way
 * docs/research/apm.md counts a player's, and holds back the commands that
 * would take more actions than the budget of ADR 0008 allows, to send them
 * later in order. Knows nothing of the engine, so test_budget.cpp can run it
 * alone. GPL-2.0-or-later. */

#ifndef REASON8_BUDGET_H
#define REASON8_BUDGET_H

#include <algorithm>
#include <cstddef>
#include <deque>
#include <functional>
#include <list>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace reason8 {

constexpr int FRAMES_PER_SECOND = 30;
constexpr int FRAMES_PER_MINUTE = 60 * FRAMES_PER_SECOND;
/* A command counts only if one of its units got no command in this many
 * frames before, as in BAR's APM gadget and reason8.analysis.apm. */
constexpr int SPAM_FRAMES = 7;

struct Window {
	int frames;      // length of the window
	int cap;         // most actions in any window of that length
	int untilFrame;  // the window applies while it ends before this frame; 0 = always
};

/* ADR 0008, skill band 30-40: any 1 s, any 10 s, any 60 s (40 in the first two
 * minutes, 90 after) and the game average of 50 a minute over any 5 minutes. */
inline std::vector<Window> Band30To40()
{
	return {
		{1 * FRAMES_PER_SECOND, 11, 0},
		{10 * FRAMES_PER_SECOND, 50, 0},
		{FRAMES_PER_MINUTE, 40, 2 * FRAMES_PER_MINUTE},
		{FRAMES_PER_MINUTE, 90, 0},
		{5 * FRAMES_PER_MINUTE, 250, 0},
	};
}

/* Which commands count as actions, and whether one more fits the budget.
 *
 * Every window is kept exactly, and spending is paced too: each window also
 * has a bucket that holds up to a quarter of its cap and refills at the rate
 * that spends the other three quarters evenly over the window. An action
 * needs a whole token in every bucket. Without pacing a busy AI spends a
 * window's cap in a few seconds and then has to wait for the rest of it: in a
 * test with a command every other frame, two minutes at a time once the
 * 5-minute budget was used up. Paced, it acts every second or two. */
class ActionCounter {
public:
	explicit ActionCounter(std::vector<Window> windows) : windows(std::move(windows))
	{
		for (const Window& window : this->windows) {
			longest = std::max(longest, window.frames);
			Bucket bucket;
			bucket.size = std::max(1.0, window.cap / 4.0);
			const double refill = window.cap > bucket.size ? window.cap - bucket.size : window.cap;
			bucket.perFrame = refill / window.frames;
			bucket.tokens = bucket.size;
			buckets.push_back(bucket);
		}
	}

	/* Whether a command to `unitId` sent at `frame` would count as an action. */
	bool Counts(int unitId, int frame) const
	{
		if (lastActionFrame == frame) {
			return false;
		}
		const auto ignored = ignoredUntil.find(unitId);
		return ignored == ignoredUntil.end() || ignored->second <= frame;
	}

	/* Whether one more action at `frame` stays within every window, and its
	 * pace. */
	bool Fits(int frame) const
	{
		for (std::size_t index = 0; index < windows.size(); ++index) {
			const Window& window = windows[index];
			if (!Applies(window, frame)) {
				continue;
			}
			if (InWindow(frame, window.frames) + 1 > window.cap || buckets[index].At(frame) < 1.0 - 1e-9) {
				return false;
			}
		}
		return true;
	}

	/* Records a command sent to `unitId` at `frame`; true when it was an action. */
	bool Record(int unitId, int frame)
	{
		const bool counted = Counts(unitId, frame);
		ignoredUntil[unitId] = frame + SPAM_FRAMES;
		if (counted) {
			lastActionFrame = frame;
			actionFrames.push_back(frame);
			while (!actionFrames.empty() && actionFrames.front() <= frame - longest) {
				actionFrames.pop_front();
			}
			for (std::size_t index = 0; index < windows.size(); ++index) {
				if (Applies(windows[index], frame)) {
					Bucket& bucket = buckets[index];
					bucket.tokens = bucket.At(frame) - 1.0;
					bucket.frame = frame;
				}
			}
		}
		return counted;
	}

private:
	struct Bucket {
		double size = 1.0;
		double perFrame = 0.0;
		double tokens = 1.0;
		int frame = 0;  // when `tokens` was taken

		double At(int when) const { return std::min(size, tokens + (when - frame) * perFrame); }
	};

	static bool Applies(const Window& window, int frame)
	{
		return window.untilFrame == 0 || frame < window.untilFrame;
	}

	int InWindow(int frame, int frames) const
	{
		int count = 0;
		for (auto it = actionFrames.rbegin(); it != actionFrames.rend() && *it > frame - frames; ++it) {
			++count;
		}
		return count;
	}

	std::vector<Window> windows;
	std::vector<Bucket> buckets;  // by window
	int longest = 0;
	std::unordered_map<int, int> ignoredUntil;  // unit -> first frame a command counts again
	std::deque<int> actionFrames;               // within the longest window
	int lastActionFrame = -1;
};

struct Tally {
	long seen = 0;       // unit commands the AI gave
	long sentAtOnce = 0;  // sent in the frame they were given
	long sentLater = 0;   // held, then sent
	long deferred = 0;    // held at least one frame
	long collapsed = 0;   // held, then replaced by a newer order to the same unit
	long dropped = 0;     // held, then thrown away because the queue was full
	long failed = 0;      // held, then refused by the engine (the unit was gone)
	long actions = 0;     // commands sent that counted as actions
	int worstDelay = 0;   // most frames a command was held
	std::vector<int> actionFrames;  // frames of the actions
};

/* Holds the commands that do not fit the budget and sends them later, in the
 * order they were given. Commands to one unit keep their order; a unit with a
 * held command has every later command held behind it. A new order that
 * replaces a unit's queue (`supersedes`) takes the place of the held orders to
 * that unit that it would replace (`collapsible`), since they would be gone as
 * soon as it arrived. When `capacity` commands are held, the oldest is
 * dropped and counted. */
template <typename Payload>
class Throttle {
public:
	using Send = std::function<int(Payload&)>;  // returns the engine's result, 0 = accepted

	Throttle(ActionCounter counter, std::size_t capacity, Send send)
		: counter(std::move(counter)), capacity(capacity), send(std::move(send))
	{
	}

	/* A command given at `frame`; returns the engine's result when it was sent
	 * at once, 0 when it is held. */
	int Submit(int frame, int unitId, bool supersedes, bool collapsible, Payload payload)
	{
		Count([](Tally& tally) { ++tally.seen; });
		if (supersedes && heldByUnit.count(unitId) != 0) {
			for (auto it = held.begin(); it != held.end();) {
				if (it->unitId == unitId && it->collapsible) {
					Count([](Tally& tally) { ++tally.collapsed; });
					Forget(unitId);
					it = held.erase(it);
				} else {
					++it;
				}
			}
		}
		if (heldByUnit.count(unitId) == 0 && (!counter.Counts(unitId, frame) || counter.Fits(frame))) {
			Count([](Tally& tally) { ++tally.sentAtOnce; });
			return Dispatch(unitId, frame, payload);
		}
		if (held.size() >= capacity) {
			Count([](Tally& tally) { ++tally.dropped; });
			Forget(held.front().unitId);
			held.pop_front();
		}
		Count([](Tally& tally) { ++tally.deferred; });
		++heldByUnit[unitId];
		held.push_back({unitId, frame, collapsible, std::move(payload)});
		return 0;
	}

	/* Sends what fits at `frame`, oldest first. Call once a frame, before the AI
	 * gives that frame's commands. */
	void Update(int frame)
	{
		if (held.empty()) {
			return;
		}
		std::unordered_set<int> blocked;
		for (auto it = held.begin(); it != held.end();) {
			if (blocked.count(it->unitId) != 0) {
				++it;
				continue;
			}
			if (counter.Counts(it->unitId, frame) && !counter.Fits(frame)) {
				blocked.insert(it->unitId);
				++it;
				continue;
			}
			const int delay = frame - it->frame;
			Count([delay](Tally& tally) {
				++tally.sentLater;
				tally.worstDelay = std::max(tally.worstDelay, delay);
			});
			if (Dispatch(it->unitId, frame, it->payload) != 0) {
				Count([](Tally& tally) { ++tally.failed; });
			}
			Forget(it->unitId);
			it = held.erase(it);
		}
	}

	std::size_t Held() const { return held.size(); }
	const Tally& Total() const { return total; }

	/* The tally since the last call (or the start), and starts a new one. */
	Tally TakeMinute()
	{
		Tally taken = std::move(minute);
		minute = Tally();
		return taken;
	}

private:
	struct Entry {
		int unitId;
		int frame;  // when the AI gave it
		bool collapsible;
		Payload payload;
	};

	template <typename Change>
	void Count(Change change)
	{
		change(total);
		change(minute);
	}

	int Dispatch(int unitId, int frame, Payload& payload)
	{
		if (counter.Record(unitId, frame)) {
			Count([frame](Tally& tally) {
				++tally.actions;
				tally.actionFrames.push_back(frame);
			});
		}
		return send(payload);
	}

	void Forget(int unitId)
	{
		const auto found = heldByUnit.find(unitId);
		if (found != heldByUnit.end() && --found->second == 0) {
			heldByUnit.erase(found);
		}
	}

	ActionCounter counter;
	std::size_t capacity;
	Send send;
	std::list<Entry> held;
	std::unordered_map<int, int> heldByUnit;
	Tally total;
	Tally minute;
};

}  // namespace reason8

#endif  // REASON8_BUDGET_H
