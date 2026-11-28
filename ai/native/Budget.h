/* Reason8 command budget: counts a team's unit commands as actions, the way
 * docs/research/apm.md counts a player's (one action for each kind of order in
 * a frame, ADR 0008), and holds back the commands that
 * would take more actions than the budget of ADR 0008 allows, to send them
 * later in order. Knows nothing of the engine, so test_budget.cpp can run it
 * alone. GPL-2.0-or-later. */

#ifndef REASON8_BUDGET_H
#define REASON8_BUDGET_H

#include <algorithm>
#include <cstddef>
#include <cstdint>
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

/* A kind of order: the command, the unit it builds and its options, without
 * its parameters or units (Governor.cpp makes it from a command). Every kind
 * in a frame is one action, however many units or places it goes to. */
using Kind = std::uint64_t;

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
		{1 * FRAMES_PER_SECOND, 14, 0},
		{10 * FRAMES_PER_SECOND, 60, 0},
		{FRAMES_PER_MINUTE, 40, 2 * FRAMES_PER_MINUTE},
		{FRAMES_PER_MINUTE, 90, 0},
		{5 * FRAMES_PER_MINUTE, 250, 0},
	};
}

/* Which commands count as actions, and whether one more fits the budget.
 *
 * A command counts when no command of its kind has counted in its frame yet,
 * and one of its units got no command in the 7 frames before that frame;
 * commands of the same frame mark their units from the next frame on, so a
 * move and a shift-queued move to one unit in one frame are two actions, as
 * the two clicks they take. As in BAR's gadget, commands to a unit in the
 * frame it was finished (`Finished`) do not count: the settings an AI gives a
 * new unit at once.
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

	/* Whether a command of `kind` to `unitId` sent at `frame` would count as
	 * an action. */
	bool Counts(int unitId, int frame, Kind kind) const
	{
		if (frame == currentFrame && countedKinds.count(kind) != 0) {
			return false;
		}
		if (frame == finishedFrame && finishedThisFrame.count(unitId) != 0) {
			return false;
		}
		return IgnoredUntil(unitId, frame) <= frame;
	}

	/* `unitId` was finished at `frame`: its commands in that frame are free. */
	void Finished(int unitId, int frame)
	{
		if (frame != finishedFrame) {
			finishedThisFrame.clear();
			finishedFrame = frame;
		}
		finishedThisFrame.insert(unitId);
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

	/* Records a command of `kind` sent to `unitId` at `frame`; true when it
	 * was an action. */
	bool Record(int unitId, int frame, Kind kind)
	{
		Advance(frame);
		const bool counted = Counts(unitId, frame, kind);
		markedThisFrame.insert(unitId);
		if (counted) {
			countedKinds.insert(kind);
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

	/* The first frame a command to `unitId` counts again, as seen from `frame`. */
	int IgnoredUntil(int unitId, int frame) const
	{
		if (frame != currentFrame && markedThisFrame.count(unitId) != 0) {
			return currentFrame + SPAM_FRAMES;
		}
		const auto ignored = ignoredUntil.find(unitId);
		return ignored == ignoredUntil.end() ? frame : ignored->second;
	}

	/* Moves on to `frame`: the marks of the frame before take effect. */
	void Advance(int frame)
	{
		if (frame == currentFrame) {
			return;
		}
		for (int unitId : markedThisFrame) {
			ignoredUntil[unitId] = currentFrame + SPAM_FRAMES;
		}
		markedThisFrame.clear();
		countedKinds.clear();
		currentFrame = frame;
	}

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
	std::unordered_set<int> markedThisFrame;    // units commanded in currentFrame
	std::unordered_set<Kind> countedKinds;      // kinds counted in currentFrame
	std::unordered_set<int> finishedThisFrame;  // units finished in finishedFrame
	std::deque<int> actionFrames;               // within the longest window
	int currentFrame = -1;
	int finishedFrame = -1;
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
	int Submit(int frame, int unitId, Kind kind, bool supersedes, bool collapsible, Payload payload)
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
		if (heldByUnit.count(unitId) == 0 && (!counter.Counts(unitId, frame, kind) || counter.Fits(frame))) {
			Count([](Tally& tally) { ++tally.sentAtOnce; });
			return Dispatch(unitId, frame, kind, payload);
		}
		if (held.size() >= capacity) {
			Count([](Tally& tally) { ++tally.dropped; });
			Forget(held.front().unitId);
			held.pop_front();
		}
		Count([](Tally& tally) { ++tally.deferred; });
		++heldByUnit[unitId];
		held.push_back({unitId, frame, kind, collapsible, std::move(payload)});
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
			if (counter.Counts(it->unitId, frame, it->kind) && !counter.Fits(frame)) {
				blocked.insert(it->unitId);
				++it;
				continue;
			}
			const int delay = frame - it->frame;
			Count([delay](Tally& tally) {
				++tally.sentLater;
				tally.worstDelay = std::max(tally.worstDelay, delay);
			});
			if (Dispatch(it->unitId, frame, it->kind, it->payload) != 0) {
				Count([](Tally& tally) { ++tally.failed; });
			}
			Forget(it->unitId);
			it = held.erase(it);
		}
	}

	/* `unitId` was finished at `frame` (ActionCounter::Finished). */
	void Finished(int unitId, int frame) { counter.Finished(unitId, frame); }

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
		Kind kind;
		bool collapsible;
		Payload payload;
	};

	template <typename Change>
	void Count(Change change)
	{
		change(total);
		change(minute);
	}

	int Dispatch(int unitId, int frame, Kind kind, Payload& payload)
	{
		if (counter.Record(unitId, frame, kind)) {
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
