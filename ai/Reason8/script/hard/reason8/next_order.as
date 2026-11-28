/*
 * Reason8 next order (docs/decisions/0019): during the opening the bot, as one player,
 * decides the next order for every unit with build power that has nothing to do, as a
 * person notices an idle builder and gives it something to do, instead of playing the
 * opening table.
 *
 * On when the AI option builder_orders is "model" and our BARb library is installed; the
 * opening table (opening.as) is played otherwise. Our library (ai/native/NextOrder.cpp)
 * consults the model, which sees the team's whole state, about the idle builder, removes
 * the answers the builder can never carry out, rescales the rest and draws among those
 * of at least 10%; this script carries the order out with BARb's tasks:
 *
 *   - a unit, by a factory: a recruit task for it;
 *   - an extractor: on the next metal spot in the order players usually take them from
 *     this map and start position (USUAL_SPOTS in next_order_table.as), or where BARb would
 *     put its next one when no usual spot is left or the map has none;
 *   - a factory or any other structure: a build task next to the builder, BARb choosing
 *     the site;
 *   - a job (assist, reclaim, repair, resurrect): BARb's own task for it, with BARb's
 *     choice of target (Reason8BarbTask).
 *
 * When the library chooses nothing (no answer reaches 10%, or none is possible) or the
 * order cannot be carried out, the builder is left to BARb until BARb gives it something
 * to do; at the builder's next idle the model decides again. The model's orders end at
 * the team's first contact or at the end of the opening window, whichever comes first, as
 * the opening does (docs/decisions/0012); then BARb decides for every unit.
 *
 * Every line is logged with the prefix "Reason8 next order:", like the library's own.
 */

#include "next_order_table.as"


namespace Reason8 {

bool isModeChecked = false;
bool areModelOrders = false;
bool areModelOrdersOver = false;  // the opening is over: BARb decides for every unit

// The usual metal spots of the AI's map and position, in the order players take them
bool areUsualSpotsChosen = false;
array<float> usualX;
array<float> usualZ;
// a usual spot is the game's metal spot nearest to it, if one is this close
const float USUAL_SPOT_RADIUS = 200.f;

// BARb's task type for each unit that a task builds (BUILD_TASKS)
bool areBuildTasksRead = false;
array<string> buildTaskUnits;
array<Task::BuildType> buildTaskTypes;

// Tasks given for an order: the builder it is for, the order, the metal spot taken (-1)
array<IUnitTask@> orderTasks;
array<int> orderUnits;
array<string> orderAnswers;
array<int> orderSpots;
// Units BARb decides for, until it gives them something to do
array<int> barbUnits;

void OrderLog(const string& in message)
{
	AiLog("Reason8 next order: team " + ai.teamId + ": " + message);
}

string Who(CCircuitUnit@ unit)
{
	return "frame " + ai.frame + ": " + unit.circuitDef.GetName() + " " + unit.id;
}

/* Whether the model decides builders' next orders in this game: decided once, from the
 * AI option, by our library. */
bool ModelOrdersMode()
{
	if (!isModeChecked) {
		isModeChecked = true;
		areModelOrders = ModelOrders();
		if (areModelOrders)
			OrderLog("the model decides the next orders of idle builders during the opening; "
				"the opening table is not played");
	}
	return areModelOrders;
}

void ReadBuildTasks()
{
	areBuildTasksRead = true;
	for (uint i = 0; i < BUILD_TASKS.length(); ++i) {
		array<string> fields = Split(BUILD_TASKS[i], " ");
		if (fields.length() == 2) {
			buildTaskUnits.insertLast(fields[0]);
			buildTaskTypes.insertLast(TaskType(fields[1]));
		}
	}
}

bool BuildTaskOf(const string& in unitName, Task::BuildType& out type)
{
	if (!areBuildTasksRead)
		ReadBuildTasks();
	const int index = buildTaskUnits.find(unitName);
	if (index < 0)
		return false;
	type = buildTaskTypes[index];
	return true;
}

/*
 * The usual metal spots of the map's position whose start is nearest to `position`,
 * chosen once, and that position and its role for the model's inputs. A row of
 * USUAL_SPOTS is "<map>|<position>|<start x> <start z>|<x> <z> ...|<role>".
 */
void ChooseUsualSpots(const AIFloat3& in position)
{
	areUsualSpotsChosen = true;
	const string mapName = ai.GetMapName();
	float nearest = -1.f;
	string chosen;
	string chosenPosition;
	string chosenRole;
	string spots;
	for (uint i = 0; i < USUAL_SPOTS.length(); ++i) {
		array<string> parts = Split(USUAL_SPOTS[i], "|");
		if (parts.length() != 5 || parts[0] != mapName)
			continue;
		array<string> start = Split(parts[2], " ");
		if (start.length() != 2)
			continue;
		const float dx = float(parseFloat(start[0])) - position.x;
		const float dz = float(parseFloat(start[1])) - position.z;
		if (nearest < 0.f || dx * dx + dz * dz < nearest) {
			nearest = dx * dx + dz * dz;
			chosen = parts[1] + " (start " + parts[2] + ")";
			chosenPosition = parts[1];
			chosenRole = parts[4];
			spots = parts[3];
		}
	}
	SetStart(chosenPosition, chosenRole);
	array<string> values = Split(spots, " ");
	for (uint i = 0; i + 1 < values.length(); i += 2) {
		usualX.insertLast(float(parseFloat(values[i])));
		usualZ.insertLast(float(parseFloat(values[i + 1])));
	}
	OrderLog("map '" + mapName + "', start " + int(position.x) + " " + int(position.z) + ": "
		+ (usualX.length() == 0 ? "no usual metal spots, BARb places extractors"
			: "position " + chosen + ", role " + (chosenRole.length() == 0 ? "unknown" : chosenRole) + ", "
			+ usualX.length() + " usual metal spots"));
}

/*
 * The next usual metal spot that has no extractor and that the AI has not ordered one on, as
 * BARb's spot index, or -1 when none is left.
 */
int NextUsualSpot(AIFloat3& out position, int& out rank)
{
	for (uint i = 0; i < usualX.length(); ++i) {
		AIFloat3 spotPosition;
		const int spot = NearestSpot(usualX[i], usualZ[i], spotPosition);
		if (spot < 0)
			return -1;
		const float dx = spotPosition.x - usualX[i];
		const float dz = spotPosition.z - usualZ[i];
		if (dx * dx + dz * dz > USUAL_SPOT_RADIUS * USUAL_SPOT_RADIUS)
			continue;  // its spot is taken by the AI already
		if (!SpotOpen(spot))
			continue;  // someone has an extractor there
		position = spotPosition;
		rank = int(i) + 1;
		return spot;
	}
	return -1;
}

bool IsJob(const string& in answer)
{
	return answer == "assist" || answer == "reclaim" || answer == "repair" || answer == "resurrect";
}

/* The task that carries out the order `answer` for a builder, or null with the reason. */
IUnitTask@ BuilderTaskFor(CCircuitUnit@ unit, const string& in answer, string& out reason, int& out spot)
{
	spot = -1;
	if (IsJob(answer)) {
		IUnitTask@ job = BarbTask(unit, answer);
		if (job is null)
			reason = "BARb has no " + answer + " task for it";
		return job;
	}
	CCircuitDef@ buildDef = GetOrderedDef(answer);
	if (buildDef is null) {
		reason = "not available";
		return null;
	}
	Task::BuildType type;
	if (!BuildTaskOf(answer, type)) {
		reason = "no BARb task builds it";
		return null;
	}
	IUnitTask@ task = null;
	if (type == Task::BuildType::MEX) {
		AIFloat3 spotPosition;
		int rank = 0;
		spot = NextUsualSpot(spotPosition, rank);
		if (spot >= 0) {
			takenSpots.insertLast(spot);
			@task = aiBuilderMgr.Enqueue(
				TaskB::Spot(type, Task::Priority::NOW, buildDef, spotPosition, spot));
			OrderLog(Who(unit) + ": " + answer + " on usual spot " + rank + " of " + usualX.length()
				+ ", BARb's spot " + spot + " at " + int(spotPosition.x) + " " + int(spotPosition.z));
		} else {
			@task = BarbTask(unit, "mex");
			if (task !is null)
				OrderLog(Who(unit) + ": " + answer + " on BARb's metal spot");
		}
		if (task is null)
			reason = "no metal spot for it";
		return task;
	}
	const AIFloat3 position = unit.GetPos(ai.frame);
	if (type == Task::BuildType::FACTORY) {
		@task = aiBuilderMgr.Enqueue(TaskB::Factory(Task::Priority::NOW, buildDef, position, null));
	} else {
		@task = aiBuilderMgr.Enqueue(TaskB::Common(type, Task::Priority::NOW, buildDef, position));
	}
	if (task is null)
		reason = "BARb did not take the task";
	return task;
}

/* The task that makes the order `answer` in a factory, or null with the reason. */
IUnitTask@ FactoryTaskFor(CCircuitUnit@ unit, const string& in answer, string& out reason)
{
	CCircuitDef@ buildDef = GetOrderedDef(answer);
	if (buildDef is null) {
		reason = "not available";
		return null;
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
	IUnitTask@ task = aiFactoryMgr.Enqueue(
		TaskS::Recruit(recruit, priority, buildDef, unit.GetPos(ai.frame), 64.f));
	if (task is null)
		reason = "BARb did not take the task";
	return task;
}

void LeaveToBarb(int unitId)
{
	if (barbUnits.find(unitId) < 0)
		barbUnits.insertLast(unitId);
}

/*
 * Called for an idle builder or factory, after its reaction delay. Returns the task for
 * the order the library chose, or null when it is left to BARb.
 */
IUnitTask@ NextOrderFor(CCircuitUnit@ unit, bool isFactory)
{
	if (!ModelOrdersMode() || areModelOrdersOver)
		return null;
	if (barbUnits.find(unit.id) >= 0)
		return null;  // BARb has not given it anything yet since it was left to BARb
	if (!areUsualSpotsChosen)
		ChooseUsualSpots(unit.GetPos(ai.frame));
	const string answer = NextOrder(unit);
	if (answer.length() == 0) {
		LeaveToBarb(unit.id);
		return null;
	}
	string reason;
	int spot = -1;
	IUnitTask@ task = isFactory ? FactoryTaskFor(unit, answer, reason)
		: BuilderTaskFor(unit, answer, reason, spot);
	if (task is null) {
		OrderFailed(unit, answer, reason);
		LeaveToBarb(unit.id);
		return null;
	}
	orderTasks.insertLast(task);
	orderUnits.insertLast(unit.id);
	orderAnswers.insertLast(answer);
	orderSpots.insertLast(spot);
	return task;
}

/* Called with the task BARb gave a unit that got no order from the model. */
void BarbGave(CCircuitUnit@ unit, IUnitTask@ task)
{
	if (task is null || task.GetType() == Task::Type::WAIT)
		return;
	if (areModelOrders && !areModelOrdersOver)
		BarbOrdered(unit, task);  // an order of the bot all the same, for the model's history
	const int index = barbUnits.find(unit.id);
	if (index >= 0)
		barbUnits.removeAt(index);  // at its next idle the model decides again
}

/*
 * Called when a builder or factory task ends. A task given for an order that ends
 * undone could not be carried out: its unit is left to BARb, and its metal spot is free
 * to be ordered again.
 */
void OrderTaskEnded(IUnitTask@ task, bool done)
{
	for (int i = int(orderTasks.length()) - 1; i >= 0; --i) {
		if (orderTasks[i] !is task)
			continue;
		const int unitId = orderUnits[i];
		const string answer = orderAnswers[i];
		const int spot = orderSpots[i];
		orderTasks.removeAt(i);
		orderUnits.removeAt(i);
		orderAnswers.removeAt(i);
		orderSpots.removeAt(i);
		if (done || areModelOrdersOver)
			continue;
		if (spot >= 0 && takenSpots.find(spot) >= 0)
			takenSpots.removeAt(takenSpots.find(spot));
		CCircuitUnit@ unit = ai.GetTeamUnit(unitId);
		if (unit !is null)
			OrderFailed(unit, answer, "its task ended unfinished");
		LeaveToBarb(unitId);
	}
}

/*
 * Called when a factory is finished. Returns true when the model will decide its units,
 * so that BARb's own opener does not queue them.
 */
bool FactoryTakesModelOrders(CCircuitUnit@ factory)
{
	return ModelOrdersMode() && !areModelOrdersOver;
}

void EndModelOrders(const string& in reason, const string& in detail)
{
	areModelOrdersOver = true;
	barbUnits.resize(0);
	OrderLog("model orders ended at frame " + ai.frame + ", " + reason + ": " + detail + "; BARb takes over");
}

/* Called once a second from main.as (through Update) while the model decides. */
void UpdateModelOrders()
{
	if (areModelOrdersOver)
		return;
	LogStateEvery30Seconds();
	const int contactFrame = FirstContactFrame();
	if (contactFrame >= 0) {
		EndModelOrders("contact", "first contact at frame " + contactFrame + ", " + FirstContact());
		return;
	}
	if (ai.frame >= OPENING_WINDOW_SECONDS * SECOND)
		EndModelOrders("time", "the game is past the opening window of " + OPENING_WINDOW_SECONDS + " s");
}

}  // namespace Reason8
