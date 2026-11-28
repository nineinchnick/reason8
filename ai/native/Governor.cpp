/* Reason8 command governor; see Governor.h. GPL-2.0-or-later. */

#include "Governor.h"

#include "Budget.h"
#include "Reason8Build.h"  // REASON8_ENGINE_TAG, written by ai/native/build.sh

#include "ExternalAI/Interface/AISCommands.h"
#include "ExternalAI/Interface/SSkirmishAICallback.h"

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace reason8 {

namespace {

/* Most commands held at once; past it the oldest is dropped. BARb gives a team
 * a few hundred commands a minute, and the queue empties whenever one action
 * fits the budget. */
constexpr std::size_t CAPACITY = 1024;

enum class Mode { OFF, COUNT, DEFER };

/* A copy of a command struct and of the arrays it points to, so that it can
 * be sent after the caller's memory is gone. */
struct HeldCommand {
	int topic = 0;
	std::vector<unsigned char> bytes;  // the struct
	std::vector<float> floats;         // what its float pointer points to
	std::vector<int> ints;             // what its int pointer points to
	std::ptrdiff_t floatsAt = -1;      // offset of the float pointer in the struct
	std::ptrdiff_t intsAt = -1;        // offset of the int pointer in the struct

	/* The struct, with its pointers set to the copies. */
	void* Data()
	{
		if (floatsAt >= 0) {
			float* pointer = floats.empty() ? nullptr : floats.data();
			std::memcpy(bytes.data() + floatsAt, &pointer, sizeof(pointer));
		}
		if (intsAt >= 0) {
			int* pointer = ints.empty() ? nullptr : ints.data();
			std::memcpy(bytes.data() + intsAt, &pointer, sizeof(pointer));
		}
		return bytes.data();
	}
};

template <typename Command, typename Member>
std::ptrdiff_t OffsetOf(const Command* command, Member Command::*member)
{
	return reinterpret_cast<const unsigned char*>(&(command->*member)) - reinterpret_cast<const unsigned char*>(command);
}

template <typename Command>
HeldCommand Plain(int topic, const void* data)
{
	HeldCommand held;
	held.topic = topic;
	held.bytes.resize(sizeof(Command));
	std::memcpy(held.bytes.data(), data, sizeof(Command));
	return held;
}

/* A command with a position: a pointer to three floats, or nullptr. */
template <typename Command>
HeldCommand WithPosition(int topic, const void* data, float* Command::*position)
{
	HeldCommand held = Plain<Command>(topic, data);
	const Command* command = static_cast<const Command*>(data);
	if (command->*position != nullptr) {
		held.floats.assign(command->*position, command->*position + 3);
	}
	held.floatsAt = OffsetOf(command, position);
	return held;
}

/* Whether a unit command topic is an order that goes into the unit's queue, so
 * that a new one given without shift replaces the queue. The others set a
 * state (fire state, on/off, ...) and never replace anything. */
bool IsQueuedOrder(int topic)
{
	switch (topic) {
		case COMMAND_UNIT_BUILD: case COMMAND_UNIT_STOP: case COMMAND_UNIT_MOVE: case COMMAND_UNIT_PATROL:
		case COMMAND_UNIT_FIGHT: case COMMAND_UNIT_ATTACK: case COMMAND_UNIT_ATTACK_AREA: case COMMAND_UNIT_GUARD:
		case COMMAND_UNIT_REPAIR: case COMMAND_UNIT_LOAD_UNITS: case COMMAND_UNIT_LOAD_UNITS_AREA:
		case COMMAND_UNIT_LOAD_ONTO: case COMMAND_UNIT_UNLOAD_UNITS_AREA: case COMMAND_UNIT_UNLOAD_UNIT:
		case COMMAND_UNIT_RECLAIM_UNIT: case COMMAND_UNIT_RECLAIM_AREA: case COMMAND_UNIT_RECLAIM_FEATURE:
		case COMMAND_UNIT_D_GUN: case COMMAND_UNIT_D_GUN_POS: case COMMAND_UNIT_RESTORE_AREA:
		case COMMAND_UNIT_RESURRECT: case COMMAND_UNIT_RESURRECT_AREA: case COMMAND_UNIT_CAPTURE:
		case COMMAND_UNIT_CAPTURE_AREA:
			return true;
		default:
			return false;
	}
}

/* A copy of a unit command; false for a topic that is not a unit command. */
bool Copy(int topic, const void* data, HeldCommand& held)
{
	switch (topic) {
		case COMMAND_UNIT_BUILD: held = WithPosition(topic, data, &SBuildUnitCommand::buildPos_posF3); return true;
		case COMMAND_UNIT_STOP: held = Plain<SStopUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_WAIT: held = Plain<SWaitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_WAIT_TIME: held = Plain<STimeWaitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_WAIT_DEATH: held = Plain<SDeathWaitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_WAIT_SQUAD: held = Plain<SSquadWaitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_WAIT_GATHER: held = Plain<SGatherWaitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_MOVE: held = WithPosition(topic, data, &SMoveUnitCommand::toPos_posF3); return true;
		case COMMAND_UNIT_PATROL: held = WithPosition(topic, data, &SPatrolUnitCommand::toPos_posF3); return true;
		case COMMAND_UNIT_FIGHT: held = WithPosition(topic, data, &SFightUnitCommand::toPos_posF3); return true;
		case COMMAND_UNIT_ATTACK: held = Plain<SAttackUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_ATTACK_AREA: held = WithPosition(topic, data, &SAttackAreaUnitCommand::toAttackPos_posF3); return true;
		case COMMAND_UNIT_GUARD: held = Plain<SGuardUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_GROUP_ADD: held = Plain<SGroupAddUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_GROUP_CLEAR: held = Plain<SGroupClearUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_REPAIR: held = Plain<SRepairUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_SET_FIRE_STATE: held = Plain<SSetFireStateUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_SET_MOVE_STATE: held = Plain<SSetMoveStateUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_SET_BASE: held = WithPosition(topic, data, &SSetBaseUnitCommand::basePos_posF3); return true;
		case COMMAND_UNIT_SELF_DESTROY: held = Plain<SSelfDestroyUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_LOAD_UNITS: {
			held = Plain<SLoadUnitsUnitCommand>(topic, data);
			const auto* command = static_cast<const SLoadUnitsUnitCommand*>(data);
			if (command->toLoadUnitIds != nullptr && command->toLoadUnitIds_size > 0) {
				held.ints.assign(command->toLoadUnitIds, command->toLoadUnitIds + command->toLoadUnitIds_size);
			}
			held.intsAt = OffsetOf(command, &SLoadUnitsUnitCommand::toLoadUnitIds);
			return true;
		}
		case COMMAND_UNIT_LOAD_UNITS_AREA: held = WithPosition(topic, data, &SLoadUnitsAreaUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_LOAD_ONTO: held = Plain<SLoadOntoUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_UNLOAD_UNITS_AREA: held = WithPosition(topic, data, &SUnloadUnitsAreaUnitCommand::toPos_posF3); return true;
		case COMMAND_UNIT_UNLOAD_UNIT: held = WithPosition(topic, data, &SUnloadUnitCommand::toPos_posF3); return true;
		case COMMAND_UNIT_SET_ON_OFF: held = Plain<SSetOnOffUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_RECLAIM_UNIT: held = Plain<SReclaimUnitUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_RECLAIM_AREA: held = WithPosition(topic, data, &SReclaimAreaUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_CLOAK: held = Plain<SCloakUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_STOCKPILE: held = Plain<SStockpileUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_D_GUN: held = Plain<SDGunUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_D_GUN_POS: held = WithPosition(topic, data, &SDGunPosUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_RESTORE_AREA: held = WithPosition(topic, data, &SRestoreAreaUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_SET_REPEAT: held = Plain<SSetRepeatUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_SET_TRAJECTORY: held = Plain<SSetTrajectoryUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_RESURRECT: held = Plain<SResurrectUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_RESURRECT_AREA: held = WithPosition(topic, data, &SResurrectAreaUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_CAPTURE: held = Plain<SCaptureUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_CAPTURE_AREA: held = WithPosition(topic, data, &SCaptureAreaUnitCommand::pos_posF3); return true;
		case COMMAND_UNIT_SET_AUTO_REPAIR_LEVEL: held = Plain<SSetAutoRepairLevelUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_SET_IDLE_MODE: held = Plain<SSetIdleModeUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_RECLAIM_FEATURE: held = Plain<SReclaimFeatureUnitCommand>(topic, data); return true;
		case COMMAND_UNIT_CUSTOM: {
			held = Plain<SCustomUnitCommand>(topic, data);
			const auto* command = static_cast<const SCustomUnitCommand*>(data);
			if (command->params != nullptr && command->params_size > 0) {
				held.floats.assign(command->params, command->params + command->params_size);
			}
			held.floatsAt = OffsetOf(command, &SCustomUnitCommand::params);
			return true;
		}
		default:
			return false;
	}
}

/* The kind of order of a unit command (Budget.h): its topic and options, the
 * unit def of a build and the command id of a custom command, and for an
 * INSERT the inserted command's id and options, as the replay's commands are
 * told apart in reason8.analysis.apm.order_kind. */
Kind KindOf(int topic, const void* data)
{
	const auto* common = static_cast<const SStopUnitCommand*>(data);
	std::int64_t parts[4] = {topic, common->options, 0, 0};
	if (topic == COMMAND_UNIT_BUILD) {
		parts[2] = static_cast<const SBuildUnitCommand*>(data)->toBuildUnitDefId;
	} else if (topic == COMMAND_UNIT_CUSTOM) {
		const auto* custom = static_cast<const SCustomUnitCommand*>(data);
		parts[2] = custom->cmdId;
		constexpr int CMD_INSERT = 1;
		if (custom->cmdId == CMD_INSERT && custom->params != nullptr && custom->params_size >= 3) {
			parts[3] = (static_cast<std::int64_t>(custom->params[1]) << 16) ^ static_cast<std::int64_t>(custom->params[2]);
		}
	}
	Kind kind = 1469598103934665603ULL;  // FNV-1a over the parts
	for (std::int64_t part : parts) {
		kind = (kind ^ static_cast<Kind>(part)) * 1099511628211ULL;
	}
	return kind;
}

struct Governor {
	int skirmishAIId = -1;
	const SSkirmishAICallback* inner = nullptr;
	SSkirmishAICallback governed;
	Mode mode = Mode::OFF;
	int teamId = -1;
	int minute = 0;
	std::unique_ptr<Throttle<HeldCommand>> throttle;
	std::unordered_map<int, bool> mobileDefs;  // unit def -> can move
	std::map<int, long> topics;                // command topic -> commands, for the totals
	long unknownTopics = 0;                    // sent unheld: not a unit command we can copy
};

std::unordered_map<int, Governor*> governors;

void Log(const Governor& governor, const std::string& text)
{
	const std::string line = "Reason8 governor: team " + std::to_string(governor.teamId) + ": " + text;
	governor.inner->Log_log(governor.skirmishAIId, line.c_str());
}

std::string Describe(const Tally& tally, std::size_t held)
{
	return "seen " + std::to_string(tally.seen) + ", sent at once " + std::to_string(tally.sentAtOnce)
		+ ", sent later " + std::to_string(tally.sentLater) + ", deferred " + std::to_string(tally.deferred)
		+ ", collapsed " + std::to_string(tally.collapsed) + ", dropped " + std::to_string(tally.dropped)
		+ ", failed " + std::to_string(tally.failed) + ", actions " + std::to_string(tally.actions)
		+ ", worst delay " + std::to_string(tally.worstDelay) + " frames, held " + std::to_string(held);
}

void LogMinute(Governor& governor, const std::string& name)
{
	const Tally tally = governor.throttle->TakeMinute();
	Log(governor, name + ": " + Describe(tally, governor.throttle->Held()));
	std::string frames = name + " action frames:";
	for (int frame : tally.actionFrames) {
		frames += " " + std::to_string(frame);
	}
	Log(governor, frames);
}

void CloseMinutes(Governor& governor, int frame)
{
	const int minute = frame / FRAMES_PER_MINUTE;
	while (governor.minute < minute) {
		LogMinute(governor, "minute " + std::to_string(governor.minute + 1));
		++governor.minute;
	}
}

bool IsMobile(Governor& governor, int unitId)
{
	const int defId = governor.inner->Unit_getDef(governor.skirmishAIId, unitId);
	const auto found = governor.mobileDefs.find(defId);
	if (found != governor.mobileDefs.end()) {
		return found->second;
	}
	const bool mobile = defId >= 0 && governor.inner->UnitDef_getSpeed(governor.skirmishAIId, defId) > 0.f;
	governor.mobileDefs[defId] = mobile;
	return mobile;
}

int CALLING_CONV GovernedHandleCommand(int skirmishAIId, int toId, int commandId, int topic, void* data)
{
	Governor& governor = *governors.at(skirmishAIId);
	HeldCommand held;
	if (data == nullptr || !Copy(topic, data, held)) {
		return governor.inner->Engine_handleCommand(skirmishAIId, toId, commandId, topic, data);
	}
	// Every unit command struct starts with `int unitId; int groupId; short options;`.
	const auto* common = static_cast<const SStopUnitCommand*>(data);
	if (common->unitId < 0) {  // a group command: BARb gives none
		++governor.unknownTopics;
		return governor.inner->Engine_handleCommand(skirmishAIId, toId, commandId, topic, data);
	}
	const int frame = governor.inner->Game_getCurrentFrame(skirmishAIId);
	CloseMinutes(governor, frame);
	++governor.topics[topic];
	// Orders to a factory add to its queue even without shift, so only a mobile
	// unit's orders replace each other.
	const bool collapsible = IsQueuedOrder(topic) && IsMobile(governor, common->unitId);
	const bool supersedes = collapsible && (common->options & UNIT_COMMAND_OPTION_SHIFT_KEY) == 0;
	return governor.throttle->Submit(
		frame, common->unitId, KindOf(topic, data), supersedes, collapsible, std::move(held));
}

Mode ModeFromOptions(int skirmishAIId, const SSkirmishAICallback* inner)
{
	const char* value = inner->SkirmishAI_OptionValues_getValueByKey(skirmishAIId, "command_budget");
	if (value == nullptr || std::strcmp(value, "defer") == 0) {
		return Mode::DEFER;
	}
	if (std::strcmp(value, "count") == 0) {
		return Mode::COUNT;
	}
	return Mode::OFF;
}

}  // namespace

const SSkirmishAICallback* InstallGovernor(int skirmishAIId, const SSkirmishAICallback* inner)
{
	Governor* governor = new Governor();
	governor->skirmishAIId = skirmishAIId;
	governor->inner = inner;
	governor->mode = ModeFromOptions(skirmishAIId, inner);
	governor->teamId = inner->SkirmishAI_getTeamId(skirmishAIId);
	governors[skirmishAIId] = governor;

	const char* engine = inner->Engine_Version_getNormal(skirmishAIId);
	const std::string running = engine == nullptr ? "" : engine;
	const std::string builtFor = REASON8_ENGINE_TAG;
	const std::string library = "Reason8 library: team " + std::to_string(governor->teamId) + ": built for engine "
		+ builtFor + ", running in engine " + running;
	inner->Log_log(skirmishAIId, library.c_str());
	if (running.rfind(builtFor, 0) != 0) {
		const std::string mismatch = "Reason8 library: team " + std::to_string(governor->teamId)
			+ ": engine mismatch, rebuild the library for engine " + running;
		inner->Log_log(skirmishAIId, mismatch.c_str());
	}

	static const char* MODES[] = {"off", "count", "defer"};
	Log(*governor, std::string("mode ") + MODES[static_cast<int>(governor->mode)] + ", band 30-40");
	if (governor->mode == Mode::OFF) {
		return inner;
	}
	std::vector<Window> windows;
	if (governor->mode == Mode::DEFER) {
		windows = Band30To40();
	}
	governor->throttle = std::make_unique<Throttle<HeldCommand>>(
		ActionCounter(windows), CAPACITY, [governor](HeldCommand& held) {
			return governor->inner->Engine_handleCommand(
				governor->skirmishAIId, COMMAND_TO_ID_ENGINE, -1, held.topic, held.Data());
		});
	std::memcpy(&governor->governed, inner, sizeof(SSkirmishAICallback));
	governor->governed.Engine_handleCommand = GovernedHandleCommand;
	return &governor->governed;
}

void UpdateGovernor(int skirmishAIId, int frame)
{
	const auto found = governors.find(skirmishAIId);
	if (found == governors.end() || !found->second->throttle) {
		return;
	}
	CloseMinutes(*found->second, frame);
	found->second->throttle->Update(frame);
}

void ReleaseGovernor(int skirmishAIId)
{
	const auto found = governors.find(skirmishAIId);
	if (found == governors.end()) {
		return;
	}
	Governor* governor = found->second;
	if (governor->throttle) {
		const int frame = governor->inner->Game_getCurrentFrame(skirmishAIId);
		CloseMinutes(*governor, frame);
		LogMinute(*governor, "minute " + std::to_string(governor->minute + 1) + " (part)");
		Log(*governor, "total to frame " + std::to_string(frame) + ": "
			+ Describe(governor->throttle->Total(), governor->throttle->Held()));
		std::string byTopic = "commands by topic:";
		for (const auto& [topic, count] : governor->topics) {
			byTopic += " " + std::to_string(topic) + "=" + std::to_string(count);
		}
		Log(*governor, byTopic + ", not governed " + std::to_string(governor->unknownTopics));
	}
	governors.erase(found);
	delete governor;
}

const SSkirmishAICallback* EngineCallback(int skirmishAIId)
{
	const auto found = governors.find(skirmishAIId);
	return found == governors.end() ? nullptr : found->second->inner;
}

}  // namespace reason8
