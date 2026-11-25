/*
 * Reason8 opening: play a given build order, then hand back to BARb.
 *
 * An opening lists, for one side, map and start position:
 *   - the structures the commander builds, in order, by unit name;
 *   - for each factory, the first units it makes, in order, by unit name.
 * The first factory that the opening has units for makes them. The AI plays
 * the opening of its side and map whose start is nearest to its commander;
 * an opening without a map is for any map, when none is for this one.
 * The openings are data in opening_table.as, which reason8/bot/build.py
 * generates from ai/Reason8/openings.json.
 *
 * The hooks are called from manager/builder.as and manager/factory.as. When
 * there is no opening for the side, or the opening is over, they return
 * null/false and BARb's own code decides, as in stock BARb.
 *
 * Every decision is logged with the prefix "Reason8 opening:".
 */

#include "../../define.as"
#include "../../unit.as"
#include "../../task.as"
#include "opening_table.as"


namespace Reason8 {

class SStep {  // one structure for the commander, the BARb task type that builds it,
              // and where the human player placed it (x < 0: not known)
	SStep(const string& in unitName, Task::BuildType taskType, float placeX, float placeZ) {
		unit = unitName;
		type = taskType;
		x = placeX;
		z = placeZ;
	}
	SStep() {}
	string unit;
	Task::BuildType type;
	float x;
	float z;
}

class SFactoryOpening {  // the first units of one factory
	SFactoryOpening(const string& in factoryName, array<string>& in unitNames) {
		factory = factoryName;
		units = unitNames;
	}
	SFactoryOpening() {}
	string factory;
	array<string> units;
}

// The parts of `text` between the separators.
array<string> Split(const string& in text, const string& in separator)
{
	array<string> parts;
	if (text.length() == 0)
		return parts;
	uint start = 0;
	while (true) {
		const int found = text.findFirst(separator, start);
		if (found < 0) {
			parts.insertLast(text.substr(start));
			return parts;
		}
		parts.insertLast(text.substr(start, uint(found) - start));
		start = uint(found) + separator.length();
	}
	return parts;
}

Task::BuildType TaskType(const string& in name)
{
	if (name == "MEX") return Task::BuildType::MEX;
	if (name == "FACTORY") return Task::BuildType::FACTORY;
	if (name == "NANO") return Task::BuildType::NANO;
	if (name == "STORE") return Task::BuildType::STORE;
	if (name == "DEFENCE") return Task::BuildType::DEFENCE;
	if (name == "RADAR") return Task::BuildType::RADAR;
	if (name == "SONAR") return Task::BuildType::SONAR;
	if (name == "CONVERT") return Task::BuildType::CONVERT;
	return Task::BuildType::ENERGY;
}

/*
 * An opening as reason8/bot/build.py writes it: the steps and factories are strings
 * ("unit TYPE x z;..." and "factory:unit,unit;..."), turned into arrays by Decode() for
 * the opening that is played only.
 */
class SOpening {
	SOpening(const string& in sideName, const string& in mapName, const string& in positionName,
			float x, float z, const string& in encodedSteps, const string& in encodedFactories)
	{
		side = sideName;
		map = mapName;
		position = positionName;
		startX = x;
		startZ = z;
		steps = encodedSteps;
		factoryText = encodedFactories;
	}
	SOpening() {}
	string side;
	string map;  // empty: any map
	string position;
	float startX;
	float startZ;
	string steps;
	string factoryText;
	array<SStep> commander;
	array<SFactoryOpening> factories;

	void Decode()
	{
		array<string> encoded = Split(steps, ";");
		for (uint i = 0; i < encoded.length(); ++i) {
			array<string> fields = Split(encoded[i], " ");
			if (fields.length() == 4)
				commander.insertLast(SStep(fields[0], TaskType(fields[1]),
					float(parseInt(fields[2])), float(parseInt(fields[3]))));
		}
		array<string> encodedFactories = Split(factoryText, ";");
		for (uint i = 0; i < encodedFactories.length(); ++i) {
			array<string> parts = Split(encodedFactories[i], ":");
			if (parts.length() == 2)
				factories.insertLast(SFactoryOpening(parts[0], Split(parts[1], ",")));
		}
	}
}

// A step is skipped after this many failed tries (task aborted, or BARb offered something else)
const int MAX_TRIES = 5;

bool isOpeningChosen = false;
SOpening@ opening = null;
uint commanderStep = 0;
int tries = 0;
int retryFrame = 0;  // a failed step is tried again from this frame on
IUnitTask@ commanderTask = null;  // the task of the current commander step
CCircuitUnit@ openingFactory = null;  // the factory that makes the opening's units
array<string> factoryUnits;
uint factoryStep = 0;
int factoryTries = 0;
IUnitTask@ factoryTask = null;  // the task of the current factory unit

void Log(const string& in message)
{
	AiLog("Reason8 opening: team " + ai.teamId + ": " + message);
}

/*
 * The opening to play, chosen once: of the openings for the AI's side and map,
 * the one whose start is nearest to `position` (the commander's place at the
 * start); without one for the map, the first for the side and any map.
 */
SOpening@ GetOpening(const AIFloat3& in position_)
{
	if (isOpeningChosen)
		return opening;
	isOpeningChosen = true;

	const string side = ai.GetSideName();
	const string mapName = ai.GetMapName();
	array<SOpening> openings = MakeOpenings();
	// the position: of the openings for the side and map, the one whose start is nearest
	float nearest = -1.f;
	string position;
	for (uint i = 0; i < openings.length(); ++i) {
		if (openings[i].side != side || openings[i].map != mapName)
			continue;
		const float dx = openings[i].startX - position_.x;
		const float dz = openings[i].startZ - position_.z;
		const float distance = dx * dx + dz * dz;  // squared
		if (nearest < 0.f || distance < nearest) {
			nearest = distance;
			position = openings[i].position;
		}
	}
	// the opening: one of the position's openings, at random
	array<uint> variants;
	for (uint i = 0; i < openings.length(); ++i) {
		if (openings[i].side == side && openings[i].map == mapName && openings[i].position == position)
			variants.insertLast(i);
	}
	int variant = -1;
	if (variants.length() > 0) {
		// teams that start in the same second share the random sequence: add the team
		variant = (AiRandom(0, 9999) + ai.teamId) % int(variants.length());
		@opening = openings[variants[variant]];
	}
	for (uint i = 0; opening is null && i < openings.length(); ++i) {
		if (openings[i].side == side && openings[i].map.length() == 0)
			@opening = openings[i];
	}
	if (opening !is null)
		opening.Decode();
	Log("side '" + side + "', map '" + mapName + "', start "
		+ int(position_.x) + " " + int(position_.z) + ": "
		+ (opening is null ? "no opening, BARb plays its own"
			: (opening.map.length() == 0 ? "the opening for any map"
				: "position " + opening.position + " (start " + int(opening.startX) + " "
					+ int(opening.startZ) + "), opening " + (variant + 1) + " of " + variants.length())
				+ ", " + opening.commander.length() + " commander steps, "
				+ opening.factories.length() + " factories"));
	return opening;
}

/*
 * The unit to build, or null when the game does not have it or BARb's limit
 * for it is reached. BARb's configs hold a unit back until a given time
 * ("since" in behaviour.json); an opening is allowed to order it earlier.
 */
CCircuitDef@ GetOrderedDef(const string& in unitName)
{
	CCircuitDef@ buildDef = ai.GetCircuitDef(unitName);
	if (buildDef is null) {
		Log("unknown unit '" + unitName + "'");
		return null;
	}
	if (buildDef.sinceFrame > ai.frame) {
		Log("lifting BARb's timer on " + unitName + " (was " + (buildDef.sinceFrame / SECOND) + " s)");
		buildDef.sinceFrame = 0;
	}
	if (!buildDef.IsAvailable(ai.frame)) {
		Log(unitName + " is not available (BARb's limit reached, or disabled)");
		return null;
	}
	return buildDef;
}

array<int> takenSpots;  // metal spots the opening has asked for

/*
 * The game's metal spot nearest to (x, z) that the opening has not asked for yet,
 * or -1. BAR publishes its spots as game rules (mex_count, mex_x1, mex_z1, ...),
 * and BARb reads them in that order, so spot i of the game is BARb's spot i - 1.
 */
int NearestSpot(float x, float z, AIFloat3& out position)
{
	const int count = int(ai.GetGameRulesParam("mex_count", -1.f));
	int best = -1;
	float bestDistance = 0.f;
	for (int i = 1; i <= count; ++i) {
		if (takenSpots.find(i - 1) >= 0)
			continue;
		const float spotX = ai.GetGameRulesParam("mex_x" + i, 0.f);
		const float spotZ = ai.GetGameRulesParam("mex_z" + i, 0.f);
		const float distance = (spotX - x) * (spotX - x) + (spotZ - z) * (spotZ - z);
		if (best < 0 || distance < bestDistance) {
			best = i - 1;
			bestDistance = distance;
			position = AIFloat3(spotX, ai.GetGameRulesParam("mex_y" + i, 0.f), spotZ);
		}
	}
	return best;
}

void NextCommanderStep()
{
	++commanderStep;
	tries = 0;
	@commanderTask = null;
	if (opening !is null && commanderStep == opening.commander.length())
		Log("commander steps done at frame " + ai.frame + ", BARb takes over");
}

/*
 * Called for an idle builder. Returns the commander's next opening task, or
 * null when BARb should decide (not the commander, no opening, opening over).
 */
IUnitTask@ MakeCommanderTask(CCircuitUnit@ unit)
{
	if (!unit.circuitDef.IsRoleAny(Unit::Role::COMM.mask))
		return null;
	SOpening@ plan = GetOpening(unit.GetPos(ai.frame));
	if (plan is null)
		return null;
	if (commanderTask !is null)
		return commanderTask;  // the commander dropped the current step and is idle again
	if (ai.frame < retryFrame)
		return aiBuilderMgr.Enqueue(TaskB::Wait(retryFrame - ai.frame));

	while (commanderStep < plan.commander.length()) {
		const string unitName = plan.commander[commanderStep].unit;
		const Task::BuildType type = plan.commander[commanderStep].type;
		CCircuitDef@ buildDef = GetOrderedDef(unitName);
		if (buildDef is null || tries >= MAX_TRIES) {
			Log("step " + (commanderStep + 1) + " " + unitName + ": skipped");
			NextCommanderStep();
			continue;
		}

		const SStep@ planned = plan.commander[commanderStep];
		if (type == Task::BuildType::MEX && planned.x >= 0.f) {
			// the free metal spot nearest to where the human built this extractor
			AIFloat3 spotPosition;
			const int spot = NearestSpot(planned.x, planned.z, spotPosition);
			if (spot >= 0) {
				takenSpots.insertLast(spot);
				@commanderTask = aiBuilderMgr.Enqueue(
					TaskB::Spot(type, Task::Priority::NOW, buildDef, spotPosition, spot));
				++tries;
				Log("step " + (commanderStep + 1) + " " + unitName + ": spot " + spot + " at "
					+ int(spotPosition.x) + " " + int(spotPosition.z) + ", frame " + ai.frame);
				return commanderTask;
			}
		}
		if (type == Task::BuildType::MEX) {
			// without a place or the game's spots, BARb picks the task; it is taken
			// only when it is an extractor of the ordered type.
			IUnitTask@ offer = aiBuilderMgr.DefaultMakeTask(unit);
			if (offer is null || offer.GetType() != Task::Type::BUILDER)
				return offer;  // BARb is not ready (path query, or a short wait)
			IBuilderTask@ build = cast<IBuilderTask>(offer);
			if (build !is null && build.GetBuildType() == Task::BuildType::MEX
				&& build.buildDef is buildDef)
			{
				@commanderTask = offer;
				Log("step " + (commanderStep + 1) + " " + unitName + ": BARb's extractor task, frame " + ai.frame);
				return offer;
			}
			++tries;
			Log("step " + (commanderStep + 1) + " " + unitName + ": BARb offered another task, try " + tries);
			return aiBuilderMgr.Enqueue(TaskB::Wait(SECOND));
		}

		// where the human placed it; after a failure (BARb found no site there), or
		// when the place is not known, next to the builder
		const AIFloat3 position = (planned.x >= 0.f && tries == 0)
			? AIFloat3(planned.x, 0.f, planned.z) : unit.GetPos(ai.frame);
		if (type == Task::BuildType::FACTORY) {
			@commanderTask = aiBuilderMgr.Enqueue(
				TaskB::Factory(Task::Priority::NOW, buildDef, position, null));
		} else {
			@commanderTask = aiBuilderMgr.Enqueue(
				TaskB::Common(type, Task::Priority::NOW, buildDef, position));
		}
		++tries;
		Log("step " + (commanderStep + 1) + " " + unitName + ": task queued, frame " + ai.frame);
		return commanderTask;
	}
	return null;
}

/*
 * Called when a builder task ends. A finished step moves the opening on; a
 * failed one is tried again (up to MAX_TRIES).
 */
void CommanderTaskRemoved(IUnitTask@ task, bool done)
{
	if (commanderTask is null || task !is commanderTask)
		return;
	if (done) {
		Log("step " + (commanderStep + 1) + ": finished, frame " + ai.frame);
		NextCommanderStep();
	} else {
		Log("step " + (commanderStep + 1) + ": task failed, frame " + ai.frame);
		@commanderTask = null;
		// a task that fails at once (no place to build it) would use up its tries in a
		// second; wait longer after each failure
		retryFrame = ai.frame + 2 * SECOND * tries;
	}
}

/*
 * Called when a factory is finished. When the opening lists units for it,
 * remembers the factory and returns true; returns false when BARb's own opener
 * should be used.
 */
bool StartFactoryOpening(CCircuitUnit@ factory)
{
	SOpening@ plan = GetOpening(factory.GetPos(ai.frame));
	if (plan is null || openingFactory !is null || factoryStep > 0)
		return false;

	const string factoryName = factory.circuitDef.GetName();
	for (uint i = 0; i < plan.factories.length(); ++i) {
		if (plan.factories[i].factory != factoryName)
			continue;

		@openingFactory = factory;
		factoryUnits = plan.factories[i].units;
		string listed = "";
		for (uint j = 0; j < factoryUnits.length(); ++j)
			listed += " " + factoryUnits[j];
		Log("factory " + factoryName + ": will make" + listed + ", frame " + ai.frame);
		return true;
	}
	Log("factory " + factoryName + ": not in the opening, BARb's opener is used");
	return false;
}

void NextFactoryStep()
{
	++factoryStep;
	factoryTries = 0;
	@factoryTask = null;
	if (factoryStep == factoryUnits.length()) {
		Log("factory units done at frame " + ai.frame + ", BARb takes over");
		@openingFactory = null;
	}
}

/*
 * Called for an idle factory. Returns the task for the opening's next unit,
 * or null when BARb should decide. One unit is queued at a time, so that a
 * task BARb gives up on can be queued again without changing the order.
 */
IUnitTask@ MakeFactoryTask(CCircuitUnit@ unit)
{
	if (openingFactory is null || unit !is openingFactory)
		return null;
	if (factoryTask !is null)
		return factoryTask;  // the factory dropped the current unit and is idle again

	while (factoryStep < factoryUnits.length()) {
		const string unitName = factoryUnits[factoryStep];
		CCircuitDef@ buildDef = GetOrderedDef(unitName);
		if (buildDef is null || factoryTries >= MAX_TRIES) {
			Log("factory unit " + (factoryStep + 1) + " " + unitName + ": skipped");
			NextFactoryStep();
			continue;
		}

		// same priorities as BARb's own opener
		Task::Priority priority;
		Task::RecruitType recruit;
		if (buildDef.IsRoleAny(Unit::Role::BUILDER.mask)) {
			priority = Task::Priority::NORMAL;
			recruit  = Task::RecruitType::BUILDPOWER;
		} else {
			priority = Task::Priority::HIGH;
			recruit  = Task::RecruitType::FIREPOWER;
		}
		@factoryTask = aiFactoryMgr.Enqueue(
			TaskS::Recruit(recruit, priority, buildDef, unit.GetPos(ai.frame), 64.f));
		++factoryTries;
		Log("factory unit " + (factoryStep + 1) + " " + unitName + ": task queued, frame " + ai.frame);
		return factoryTask;
	}
	return null;
}

/*
 * Called when a factory task ends. A finished unit moves the opening on; a
 * failed one is queued again (up to MAX_TRIES).
 */
void FactoryTaskRemoved(IUnitTask@ task, bool done)
{
	if (factoryTask is null || task !is factoryTask)
		return;
	if (done) {
		Log("factory unit " + (factoryStep + 1) + ": done, frame " + ai.frame);
		NextFactoryStep();
	} else {
		Log("factory unit " + (factoryStep + 1) + ": task failed, frame " + ai.frame);
		@factoryTask = null;
	}
}

/*
 * Called when a factory is lost. Without its factory the rest of the
 * opening's units are dropped.
 */
void FactoryRemoved(CCircuitUnit@ unit)
{
	if (openingFactory is null || unit !is openingFactory)
		return;
	Log("factory lost at frame " + ai.frame + ", BARb takes over");
	@openingFactory = null;
	@factoryTask = null;
}

}  // namespace Reason8
