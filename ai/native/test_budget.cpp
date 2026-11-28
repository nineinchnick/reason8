/* Tests of Budget.h without the engine. ai/native/build.sh compiles and runs
 * it before it builds the library:
 *
 *   g++ -std=c++20 -I ai/native ai/native/test_budget.cpp -o test_budget && ./test_budget
 *
 * GPL-2.0-or-later. */

#include "Budget.h"

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using reason8::ActionCounter;
using reason8::Throttle;
using reason8::Window;

namespace {

int failures = 0;

void Expect(bool condition, const std::string& what, int line)
{
	if (!condition) {
		std::fprintf(stderr, "test_budget.cpp:%d: %s\n", line, what.c_str());
		++failures;
	}
}

#define EXPECT(condition) Expect((condition), #condition, __LINE__)

/* A payload that says which command it is; `sent` keeps the order they left. */
struct Sent {
	std::vector<int> ids;
	std::vector<int> frames;
};

Throttle<int> MakeThrottle(std::vector<Window> windows, std::size_t capacity, Sent& sent, const int& frame)
{
	return Throttle<int>(ActionCounter(std::move(windows)), capacity, [&sent, &frame](int& id) {
		sent.ids.push_back(id);
		sent.frames.push_back(frame);
		return 0;
	});
}

/* Kinds of order in the tests. */
constexpr reason8::Kind MOVE = 1;
constexpr reason8::Kind QUEUED_MOVE = 2;
constexpr reason8::Kind FIRE_STATE = 3;

void CountsLikeTheGadget()
{
	ActionCounter counter({});
	EXPECT(counter.Counts(1, 10, MOVE));
	EXPECT(counter.Record(1, 10, MOVE));
	EXPECT(!counter.Counts(2, 10, MOVE));  // one action a kind and frame
	EXPECT(!counter.Record(2, 10, MOVE));
	EXPECT(!counter.Counts(1, 16, MOVE));  // unit 1 had a command 6 frames ago
	EXPECT(counter.Counts(1, 17, MOVE));   // 7 frames later it counts again
	EXPECT(!counter.Counts(2, 12, MOVE));  // unit 2 was marked at frame 10 too
	EXPECT(counter.Counts(3, 12, MOVE));
}

void CountsEachKindInAFrame()
{
	ActionCounter counter({});
	EXPECT(counter.Record(1, 10, MOVE));
	EXPECT(counter.Record(1, 10, QUEUED_MOVE));  // a path: the same unit, a second click
	EXPECT(counter.Record(2, 10, FIRE_STATE));   // another unit, another kind
	EXPECT(!counter.Record(3, 10, FIRE_STATE));  // the same kind again: the same action
	EXPECT(!counter.Counts(1, 12, FIRE_STATE));  // the frame's marks hold from the next frame
	EXPECT(counter.Counts(4, 12, FIRE_STATE));
}

void AFinishedUnitsFirstCommandsAreFree()
{
	ActionCounter counter({});
	counter.Finished(5, 100);
	EXPECT(!counter.Record(5, 100, FIRE_STATE));  // the settings of a new unit
	EXPECT(!counter.Record(5, 100, MOVE));
	EXPECT(!counter.Counts(5, 104, MOVE));        // and they mark it like any command
	EXPECT(counter.Counts(5, 107, MOVE));
	EXPECT(counter.Record(6, 100, MOVE));         // another unit in the same frame counts
	counter.Finished(7, 101);
	EXPECT(counter.Counts(5, 108, FIRE_STATE));   // the finish marks only its own frame
	EXPECT(counter.Counts(7, 108, FIRE_STATE));
}

void PacesSpending()
{
	// 8 in any 10 s: a bucket of 2, refilled with one token every 50 frames
	ActionCounter counter({{300, 8, 0}});
	EXPECT(counter.Record(1, 0, MOVE));
	EXPECT(counter.Fits(1));
	EXPECT(counter.Record(2, 1, MOVE));
	EXPECT(!counter.Fits(2));  // the bucket is empty
	EXPECT(!counter.Fits(49));
	EXPECT(counter.Fits(52));
	EXPECT(counter.Record(3, 52, MOVE));
	EXPECT(!counter.Fits(53));
}

void WindowEndsAtItsFrame()
{
	ActionCounter counter({{60, 1, 60}});  // one a 2 s window, in the first 2 s only
	EXPECT(counter.Record(1, 0, MOVE));
	EXPECT(!counter.Fits(59));
	EXPECT(counter.Fits(60));  // the window no longer applies
}

void HoldsAndSendsInOrder()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{30, 1, 0}}, 100, sent, frame);
	EXPECT(throttle.Submit(frame, 1, MOVE, false, false, 101) == 0);  // the action of this second
	EXPECT(sent.ids.size() == 1);
	frame = 10;
	throttle.Submit(frame, 2, MOVE, false, false, 102);  // would be a second action: held
	throttle.Submit(frame, 2, MOVE, false, false, 103);  // behind the held one of its unit
	throttle.Submit(frame, 3, MOVE, false, false, 104);
	EXPECT(throttle.Held() == 3);
	EXPECT(sent.ids.size() == 1);
	for (frame = 11; frame < 30; ++frame) {
		throttle.Update(frame);
	}
	EXPECT(throttle.Held() == 3);
	frame = 30;
	throttle.Update(frame);  // room for one action: it and everything else this frame go
	EXPECT(throttle.Held() == 0);
	EXPECT((sent.ids == std::vector<int>{101, 102, 103, 104}));
	EXPECT(sent.frames.back() == 30);
	const reason8::Tally& total = throttle.Total();
	EXPECT(total.seen == 4);
	EXPECT(total.sentAtOnce == 1);
	EXPECT(total.sentLater == 3);
	EXPECT(total.deferred == 3);
	EXPECT(total.actions == 2);
	EXPECT(total.worstDelay == 20);
	EXPECT(total.dropped == 0);
}

void FreeCommandsPassHeldOnes()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{30, 1, 0}}, 100, sent, frame);
	throttle.Submit(frame, 1, MOVE, false, false, 101);
	frame = 3;
	throttle.Submit(frame, 2, MOVE, false, false, 102);  // an action over budget: held
	throttle.Submit(frame, 1, MOVE, false, false, 103);  // unit 1 is within its 7 frames: free
	EXPECT((sent.ids == std::vector<int>{101, 103}));
	EXPECT(throttle.Held() == 1);
}

void NewOrderCollapsesHeldOrders()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{30, 1, 0}}, 100, sent, frame);
	throttle.Submit(frame, 9, MOVE, false, false, 100);
	frame = 10;
	throttle.Submit(frame, 1, MOVE, false, true, 101);   // an order: held
	throttle.Submit(frame, 1, MOVE, false, false, 102);  // a state change: held behind it
	throttle.Submit(frame, 1, MOVE, false, true, 103);   // a queued order (shift): held
	throttle.Submit(frame, 1, MOVE, true, true, 104);    // an order that replaces the queue
	EXPECT(throttle.Held() == 2);
	EXPECT(throttle.Total().collapsed == 2);
	frame = 30;
	throttle.Update(frame);
	EXPECT((sent.ids == std::vector<int>{100, 102, 104}));
}

void SupersedingOrderTakesTheHeldOnesPlace()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{30, 1, 0}}, 100, sent, frame);
	throttle.Submit(frame, 9, MOVE, false, false, 100);
	frame = 10;
	throttle.Submit(frame, 1, MOVE, true, true, 101);  // held
	frame = 20;
	throttle.Submit(frame, 1, MOVE, true, true, 102);  // replaces it, and is held itself
	EXPECT(throttle.Held() == 1);
	frame = 30;
	throttle.Update(frame);
	EXPECT((sent.ids == std::vector<int>{100, 102}));
	EXPECT(throttle.Total().worstDelay == 10);
}

void OverflowDropsTheOldest()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{300, 1, 0}}, 2, sent, frame);
	throttle.Submit(frame, 9, MOVE, false, false, 100);
	frame = 10;
	throttle.Submit(frame, 1, MOVE, false, false, 101);
	throttle.Submit(frame, 2, MOVE, false, false, 102);
	throttle.Submit(frame, 3, MOVE, false, false, 103);
	EXPECT(throttle.Held() == 2);
	EXPECT(throttle.Total().dropped == 1);
	frame = 300;
	throttle.Update(frame);
	EXPECT((sent.ids == std::vector<int>{100, 102, 103}));
}

void HoldsAKindThatDoesNotFit()
{
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle({{30, 1, 0}}, 100, sent, frame);
	EXPECT(throttle.Submit(frame, 1, MOVE, false, false, 101) == 0);
	throttle.Submit(frame, 2, MOVE, false, false, 102);        // the same action: sent
	throttle.Submit(frame, 3, FIRE_STATE, false, false, 103);  // a second action: held
	EXPECT((sent.ids == std::vector<int>{101, 102}));
	frame = 30;
	throttle.Update(frame);
	EXPECT((sent.ids == std::vector<int>{101, 102, 103}));
	EXPECT(throttle.Total().actions == 2);
}

void StaysWithinTheBandUnderLoad()
{
	// BARb-like load: a command to one of 40 units every other frame for 10 minutes
	int frame = 0;
	Sent sent;
	auto throttle = MakeThrottle(reason8::Band30To40(), 1024, sent, frame);
	ActionCounter check({});
	std::vector<int> actions;
	for (frame = 0; frame < 10 * reason8::FRAMES_PER_MINUTE; ++frame) {
		throttle.Update(frame);
		if (frame % 2 == 0) {
			throttle.Submit(frame, (frame / 2) % 40, MOVE, false, false, frame);
		}
		throttle.TakeMinute();
	}
	const reason8::Tally& total = throttle.Total();
	EXPECT(total.dropped == 0);
	EXPECT(total.seen == static_cast<long>(sent.ids.size() + throttle.Held()));
	for (std::size_t index = 0; index < sent.ids.size(); ++index) {
		if (check.Record(sent.ids[index] / 2 % 40, sent.frames[index], MOVE)) {
			actions.push_back(sent.frames[index]);
		}
	}
	for (const Window& window : reason8::Band30To40()) {
		std::size_t first = 0;
		for (std::size_t last = 0; last < actions.size(); ++last) {
			while (actions[first] <= actions[last] - window.frames) {
				++first;
			}
			if (window.untilFrame == 0 || actions[last] < window.untilFrame) {
				EXPECT(static_cast<int>(last - first + 1) <= window.cap);
			}
		}
	}
	for (std::size_t index = 1; index < sent.ids.size(); ++index) {
		EXPECT(sent.ids[index - 1] < sent.ids[index]);  // in order
	}
}

}  // namespace

int main()
{
	CountsLikeTheGadget();
	CountsEachKindInAFrame();
	AFinishedUnitsFirstCommandsAreFree();
	HoldsAKindThatDoesNotFit();
	PacesSpending();
	WindowEndsAtItsFrame();
	HoldsAndSendsInOrder();
	FreeCommandsPassHeldOnes();
	NewOrderCollapsesHeldOrders();
	SupersedingOrderTakesTheHeldOnesPlace();
	OverflowDropsTheOldest();
	StaysWithinTheBandUnderLoad();
	if (failures != 0) {
		std::fprintf(stderr, "%d failed\n", failures);
		return EXIT_FAILURE;
	}
	std::printf("test_budget: all passed\n");
	return EXIT_SUCCESS;
}
