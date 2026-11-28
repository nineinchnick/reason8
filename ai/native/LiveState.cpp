/* Reason8 live state; see LiveState.h. GPL-2.0-or-later. */

#include "LiveState.h"

#include "Governor.h"

#include "ExternalAI/Interface/AISEvents.h"
#include "ExternalAI/Interface/SSkirmishAICallback.h"
#include "angelscript/include/angelscript.h"

#include <cstring>
#include <map>
#include <set>
#include <stdexcept>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace reason8 {

namespace {

/* Most units a team can have, for the buffer of getTeamUnits. */
constexpr int MAX_TEAM_UNITS = 10000;

/* Units built to look, whose hits are not contact: the same list as SCOUTS in
 * reason8/openings/contact.py, which defines first contact (ADR 0012). */
const std::set<std::string> SCOUTS = {
	"armfav", "armflea", "armpeep", "corfav", "corfink", "legfig", "legnavyscout", "legscout",
};

const SSkirmishAICallback* Callback(int skirmishAIId) { return EngineCallback(skirmishAIId); }

std::string UnitName(int skirmishAIId, int unitId)
{
	const SSkirmishAICallback* engine = Callback(skirmishAIId);
	const int defId = engine->Unit_getDef(skirmishAIId, unitId);
	const char* name = defId < 0 ? nullptr : engine->UnitDef_getName(skirmishAIId, defId);
	return name == nullptr ? "" : name;
}

/* The first contact of each AI's team: its frame (-1: none yet) and what was hit by what. */
struct Contact {
	int frame = -1;
	std::string hit;
};
std::unordered_map<int, Contact> contacts;

class LiveState {
public:
	explicit LiveState(int skirmishAIId) : skirmishAIId(skirmishAIId) {}

	float CurrentWind()
	{
		return Engine()->Map_getCurWind(skirmishAIId);
	}

	float Resource(const std::string& resource, const std::string& what)
	{
		const SSkirmishAICallback* engine = Engine();
		int resourceId = -1;
		if (resource == "metal") {
			resourceId = engine->getResourceByName(skirmishAIId, "Metal");
		} else if (resource == "energy") {
			resourceId = engine->getResourceByName(skirmishAIId, "Energy");
		}
		if (resourceId < 0) {
			return -1.f;
		}
		if (what == "current") {
			return engine->Economy_getCurrent(skirmishAIId, resourceId);
		}
		if (what == "storage") {
			return engine->Economy_getStorage(skirmishAIId, resourceId);
		}
		if (what == "income") {
			return engine->Economy_getIncome(skirmishAIId, resourceId);
		}
		if (what == "expense") {
			return engine->Economy_getUsage(skirmishAIId, resourceId);
		}
		if (what == "pull") {
			return engine->Economy_getPull(skirmishAIId, resourceId);
		}
		return -1.f;
	}

	int UnitCount(const std::string& unitName)
	{
		const std::map<std::string, int> standing = CountStanding();
		const auto found = standing.find(unitName);
		return found == standing.end() ? 0 : found->second;
	}

	int FirstContactFrame() { return contacts[skirmishAIId].frame; }

	/* Whether idle units wait a reaction delay: the AI option reaction_delays, on unless
	 * it says "off". */
	bool ReactionDelays()
	{
		const char* value = Engine()->SkirmishAI_OptionValues_getValueByKey(skirmishAIId, "reaction_delays");
		return value == nullptr || std::strcmp(value, "off") != 0;
	}

	std::string FirstContact() { return contacts[skirmishAIId].hit; }

	std::string Standing()
	{
		std::string text;
		for (const auto& [name, count] : CountStanding()) {
			text += (text.empty() ? "" : ", ") + name + " " + std::to_string(count);
		}
		return text;
	}

private:
	const SSkirmishAICallback* Engine() const { return EngineCallback(skirmishAIId); }

	std::map<std::string, int> CountStanding()
	{
		const SSkirmishAICallback* engine = Engine();
		std::vector<int> units(MAX_TEAM_UNITS);
		const int count = engine->getTeamUnits(skirmishAIId, units.data(), MAX_TEAM_UNITS);
		std::map<std::string, int> standing;
		for (int index = 0; index < count && index < MAX_TEAM_UNITS; ++index) {
			if (engine->Unit_isBeingBuilt(skirmishAIId, units[index])) {
				continue;
			}
			const int defId = engine->Unit_getDef(skirmishAIId, units[index]);
			if (defId < 0) {
				continue;
			}
			auto name = names.find(defId);
			if (name == names.end()) {
				const char* defName = engine->UnitDef_getName(skirmishAIId, defId);
				name = names.emplace(defId, defName == nullptr ? "" : defName).first;
			}
			++standing[name->second];
		}
		return standing;
	}

	int skirmishAIId;
	std::unordered_map<int, std::string> names;  // unit def -> name
};

std::unordered_map<int, std::unique_ptr<LiveState>> states;

}  // namespace

void UnitDamaged(int skirmishAIId, const SUnitDamagedEvent* event)
{
	Contact& contact = contacts[skirmishAIId];
	if (contact.frame >= 0) {
		return;
	}
	const SSkirmishAICallback* engine = Callback(skirmishAIId);
	std::string attacker = "unseen";
	if (event->attacker >= 0) {
		if (engine->Unit_getAllyTeam(skirmishAIId, event->attacker) == engine->Game_getMyAllyTeam(skirmishAIId)) {
			return;  // our own or an ally's
		}
		attacker = UnitName(skirmishAIId, event->attacker);
		if (attacker.empty()) {
			attacker = "unseen";
		}
	} else if (event->weaponDefId < 0) {
		return;  // no unit behind it
	}
	const std::string hit = UnitName(skirmishAIId, event->unit);
	if (SCOUTS.count(hit) > 0) {
		return;
	}
	contact.frame = engine->Game_getCurrentFrame(skirmishAIId);
	contact.hit = hit + " by " + attacker;
}

void RegisterLiveState(asIScriptEngine* engine, int skirmishAIId)
{
	std::unique_ptr<LiveState>& state = states[skirmishAIId];
	state = std::make_unique<LiveState>(skirmishAIId);
	contacts[skirmishAIId] = Contact();
	LiveState* object = state.get();
	int result = engine->RegisterGlobalFunction("float Reason8CurrentWind()", asMETHOD(LiveState, CurrentWind), asCALL_THISCALL_ASGLOBAL, object);
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("float Reason8Resource(const string& in, const string& in)", asMETHOD(LiveState, Resource), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("int Reason8UnitCount(const string& in)", asMETHOD(LiveState, UnitCount), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("string Reason8Standing()", asMETHOD(LiveState, Standing), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("int Reason8FirstContactFrame()", asMETHOD(LiveState, FirstContactFrame), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("string Reason8FirstContact()", asMETHOD(LiveState, FirstContact), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("bool Reason8ReactionDelays()", asMETHOD(LiveState, ReactionDelays), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result < 0) {
		throw std::runtime_error("Reason8: cannot register the live state for the scripts");
	}
}

}  // namespace reason8
