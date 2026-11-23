/*
 * Reason8 opening: play a given build order, then hand back to BARb.
 *
 * An opening lists, for one side:
 *   - the structures the commander builds, in order, by unit name;
 *   - for each factory, the first units it makes, in order, by unit name.
 * The first factory that the opening has units for makes them.
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

class SStep {  // one structure for the commander, and the BARb task type that builds it
	SStep(const string& in unitName, Task::BuildType taskType) {
		unit = unitName;
		type = taskType;
	}
	SStep() {}
	string unit;
	Task::BuildType type;
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

class SOpening {
	SOpening(const string& in sideName, array<SStep>& in commanderSteps,
			array<SFactoryOpening>& in factoryOpenings)
	{
		side = sideName;
		commander = commanderSteps;
		factories = factoryOpenings;
	}
	SOpening() {}
	string side;
	array<SStep> commander;
	array<SFactoryOpening> factories;
}

// A step is skipped after this many failed tries (task aborted, or BARb offered something else)
const int MAX_TRIES = 5;

bool isOpeningChosen = false;
SOpening@ opening = null;
uint commanderStep = 0;
int tries = 0;
IUnitTask@ commanderTask = null;  // the task of the current commander step
CCircuitUnit@ openingFactory = null;  // the factory that makes the opening's units
array<string> factoryUnits;
uint factoryStep = 0;
int factoryTries = 0;
IUnitTask@ factoryTask = null;  // the task of the current factory unit

void Log(const string& in message)
{
	AiLog("Reason8 opening: " + message);
}

SOpening@ GetOpening()
{
	if (isOpeningChosen)
		return opening;
	isOpeningChosen = true;

	const string side = ai.GetSideName();
	array<SOpening> openings = MakeOpenings();
	for (uint i = 0; i < openings.length(); ++i) {
		if (openings[i].side == side) {
			@opening = openings[i];
			break;
		}
	}
	Log("team " + ai.teamId + ", side '" + side + "', map '" + ai.GetMapName() + "': "
		+ (opening is null ? "no opening, BARb plays its own"
			: "" + opening.commander.length() + " commander steps, "
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
	SOpening@ plan = GetOpening();
	if (plan is null)
		return null;
	if (commanderTask !is null)
		return commanderTask;  // the commander dropped the current step and is idle again

	while (commanderStep < plan.commander.length()) {
		const string unitName = plan.commander[commanderStep].unit;
		const Task::BuildType type = plan.commander[commanderStep].type;
		CCircuitDef@ buildDef = GetOrderedDef(unitName);
		if (buildDef is null || tries >= MAX_TRIES) {
			Log("step " + (commanderStep + 1) + " " + unitName + ": skipped");
			NextCommanderStep();
			continue;
		}

		if (type == Task::BuildType::MEX) {
			// Scripts cannot see metal spots, so BARb picks the task; it is taken
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

		const AIFloat3 position = unit.GetPos(ai.frame);
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
	}
}

/*
 * Called when a factory is finished. When the opening lists units for it,
 * remembers the factory and returns true; returns false when BARb's own opener
 * should be used.
 */
bool StartFactoryOpening(CCircuitUnit@ factory)
{
	SOpening@ plan = GetOpening();
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
