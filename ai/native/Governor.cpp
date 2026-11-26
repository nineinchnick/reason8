/* Reason8 command governor; see Governor.h. GPL-2.0-or-later. */

#include "Governor.h"

#include "ExternalAI/Interface/AISCommands.h"
#include "ExternalAI/Interface/SSkirmishAICallback.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <unordered_map>

namespace reason8 {

namespace {

constexpr int FRAMES_PER_SECOND = 30;
constexpr int FRAMES_PER_MINUTE = 60 * FRAMES_PER_SECOND;
/* A command counts only if one of its units got no command in this many frames
 * before, as in BAR's APM gadget and reason8.analysis.apm.ActionCounter. */
constexpr int SPAM_FRAMES = 7;

struct Window {
	int frames;
	int cap;
	int untilFrame;  // the window applies before this frame; 0 = always
};

/* ADR 0008, skill band 30-40: any 1 s, any 10 s, any 60 s (40 in the first two
 * minutes, 90 after) and the game average of 50 a minute over any 5 minutes. */
const Window BUDGET[] = {
	{1 * FRAMES_PER_SECOND, 11, 0},
	{10 * FRAMES_PER_SECOND, 50, 0},
	{FRAMES_PER_MINUTE, 40, 2 * FRAMES_PER_MINUTE},
	{FRAMES_PER_MINUTE, 90, 0},
	{5 * FRAMES_PER_MINUTE, 250, 0},
};
constexpr int LONGEST_WINDOW = 5 * FRAMES_PER_MINUTE;

enum class Mode { OFF, COUNT, CAP };

struct Tally {
	long commands = 0;  // every unit command the AI sent (or tried to)
	long actions = 0;   // commands that counted as an action and were sent
	long dropped = 0;   // commands the cap kept from the engine
};

struct Governor {
	const SSkirmishAICallback* inner = nullptr;
	SSkirmishAICallback governed;
	Mode mode = Mode::OFF;
	int teamId = -1;
	std::unordered_map<int, int> ignoredUntil;  // unit -> first frame a command counts again
	std::deque<int> actionFrames;               // within the longest window
	int lastActionFrame = -1;
	int minute = 0;
	Tally thisMinute;
	Tally total;
	std::map<int, long> topics;  // command topic -> commands, for the totals
};

std::unordered_map<int, Governor*> governors;

bool IsUnitCommand(int topic)
{
	return (topic >= COMMAND_UNIT_BUILD && topic <= COMMAND_UNIT_CUSTOM)
		|| topic == COMMAND_UNIT_RECLAIM_FEATURE;
}

void Log(const Governor& governor, int skirmishAIId, const std::string& text)
{
	const std::string line = "Reason8 governor: team " + std::to_string(governor.teamId) + ": " + text;
	governor.inner->Log_log(skirmishAIId, line.c_str());
}

std::string Describe(const Tally& tally)
{
	return "commands " + std::to_string(tally.commands) + ", actions " + std::to_string(tally.actions)
		+ ", dropped " + std::to_string(tally.dropped);
}

void CloseMinutes(Governor& governor, int skirmishAIId, int frame)
{
	const int minute = frame / FRAMES_PER_MINUTE;
	while (governor.minute < minute) {
		Log(governor, skirmishAIId, "minute " + std::to_string(governor.minute + 1) + ": " + Describe(governor.thisMinute));
		governor.thisMinute = Tally();
		++governor.minute;
	}
}

bool WithinBudget(const Governor& governor, int frame)
{
	for (const Window& window : BUDGET) {
		if (window.untilFrame != 0 && frame >= window.untilFrame) {
			continue;
		}
		int inWindow = 0;
		for (auto it = governor.actionFrames.rbegin(); it != governor.actionFrames.rend(); ++it) {
			if (*it <= frame - window.frames) {
				break;
			}
			++inWindow;
		}
		if (inWindow + 1 > window.cap) {
			return false;
		}
	}
	return true;
}

int CALLING_CONV GovernedHandleCommand(int skirmishAIId, int toId, int commandId, int topic, void* data)
{
	Governor& governor = *governors.at(skirmishAIId);
	if (!IsUnitCommand(topic) || data == nullptr) {
		return governor.inner->Engine_handleCommand(skirmishAIId, toId, commandId, topic, data);
	}
	// Every unit command struct starts with `int unitId; int groupId;`.
	const int unitId = *static_cast<const int*>(data);
	const int frame = governor.inner->Game_getCurrentFrame(skirmishAIId);
	CloseMinutes(governor, skirmishAIId, frame);
	++governor.thisMinute.commands;
	++governor.total.commands;
	++governor.topics[topic];

	const auto ignored = governor.ignoredUntil.find(unitId);
	const bool counts = governor.lastActionFrame != frame
		&& (ignored == governor.ignoredUntil.end() || ignored->second <= frame);
	if (counts && governor.mode == Mode::CAP && !WithinBudget(governor, frame)) {
		++governor.thisMinute.dropped;
		++governor.total.dropped;
		return 0;  // CircuitAI treats a non-zero result as an error and drops the unit
	}
	governor.ignoredUntil[unitId] = frame + SPAM_FRAMES;
	if (counts) {
		++governor.thisMinute.actions;
		++governor.total.actions;
		governor.lastActionFrame = frame;
		governor.actionFrames.push_back(frame);
		while (!governor.actionFrames.empty() && governor.actionFrames.front() <= frame - LONGEST_WINDOW) {
			governor.actionFrames.pop_front();
		}
	}
	return governor.inner->Engine_handleCommand(skirmishAIId, toId, commandId, topic, data);
}

Mode ModeFromEnvironment()
{
	const char* value = std::getenv("REASON8_GOVERNOR");
	if (value == nullptr) {
		return Mode::OFF;
	}
	if (std::strcmp(value, "count") == 0) {
		return Mode::COUNT;
	}
	if (std::strcmp(value, "cap") == 0) {
		return Mode::CAP;
	}
	return Mode::OFF;
}

}  // namespace

const SSkirmishAICallback* InstallGovernor(int skirmishAIId, const SSkirmishAICallback* inner)
{
	const Mode mode = ModeFromEnvironment();
	if (mode == Mode::OFF) {
		return inner;
	}
	Governor* governor = new Governor();
	governor->inner = inner;
	governor->mode = mode;
	governor->teamId = inner->SkirmishAI_getTeamId(skirmishAIId);
	std::memcpy(&governor->governed, inner, sizeof(SSkirmishAICallback));
	governor->governed.Engine_handleCommand = GovernedHandleCommand;
	governors[skirmishAIId] = governor;
	Log(*governor, skirmishAIId, std::string("mode ") + (mode == Mode::CAP ? "cap" : "count"));
	return &governor->governed;
}

void ReleaseGovernor(int skirmishAIId)
{
	const auto found = governors.find(skirmishAIId);
	if (found == governors.end()) {
		return;
	}
	Governor* governor = found->second;
	const int frame = governor->inner->Game_getCurrentFrame(skirmishAIId);
	CloseMinutes(*governor, skirmishAIId, frame);
	Log(*governor, skirmishAIId, "minute " + std::to_string(governor->minute + 1) + " (part): " + Describe(governor->thisMinute));
	Log(*governor, skirmishAIId, "total to frame " + std::to_string(frame) + ": " + Describe(governor->total));
	std::string byTopic = "commands by topic:";
	for (const auto& [topic, count] : governor->topics) {
		byTopic += " " + std::to_string(topic) + "=" + std::to_string(count);
	}
	Log(*governor, skirmishAIId, byTopic);
	governors.erase(found);
	delete governor;
}

}  // namespace reason8
