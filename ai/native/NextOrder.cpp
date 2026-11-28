/* Reason8 next order; see NextOrder.h. GPL-2.0-or-later. */

#include "NextOrder.h"

#include "Choice.h"
#include "Governor.h"
#include "Model.h"
#include "ModelInputs.h"
#include "StandIn.h"
#include "Trees.h"

#include "CircuitAI.h"
#include "module/BuilderManager.h"
#include "module/EconomyManager.h"
#include "module/FactoryManager.h"
#include "resource/MetalManager.h"
#include "task/builder/BuilderTask.h"
#include "unit/CircuitDef.h"
#include "unit/CircuitUnit.h"

#include "ExternalAI/Interface/SSkirmishAICallback.h"
#include "ExternalAI/Interface/SSkirmishAILibrary.h"
#include "angelscript/include/angelscript.h"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <limits>
#include <memory>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <iterator>
#include <vector>

namespace reason8 {

namespace {

using circuit::CCircuitAI;
using circuit::CCircuitDef;
using circuit::CCircuitUnit;
using circuit::IBuilderTask;
using circuit::IUnitTask;

/* The learned model in the AI's folder (format reason8.builder-trees/1), copied
 * there by `reason8 bot build` when the data directory has one. */
const char* const MODEL_FILE = "reason8/builder_model.json";
/* The stand-in's table in the AI's folder, written by `reason8 bot build`: the
 * model when there is no learned one. */
const char* const STAND_IN_FILE = "reason8/stand_in.txt";
/* Answers listed in a decision's log line. */
constexpr std::size_t LOGGED_ANSWERS = 5;
/* The inputs of every this many decisions of a team are logged, from the first,
 * for `reason8 bot check` to compare with the state export. */
constexpr int INPUTS_LOGGED_EVERY = 4;
/* The state export writes the resources every this many frames, at the end of
 * the frame; the table takes the last line before the order's frame. */
constexpr int ECONOMY_FRAMES = 30;
/* The quantile of skill in training the bot plays with when the AI option skill
 * is not set (ADR 0019: high, but inside the range seen in training). */
const char* const DEFAULT_SKILL_QUANTILE = "0.9";
/* Most units a team can have, for the buffer of getTeamUnits. */
constexpr int MAX_TEAM_UNITS = 10000;

std::string Rounded(float probability)
{
	char text[16];
	std::snprintf(text, sizeof(text), "%.2f", probability);
	return text;
}

std::string Number(double value)
{
	char text[32];
	std::snprintf(text, sizeof(text), "%.9g", value);
	return text;
}

/* The learned trees behind the model interface: the inputs come from the game
 * (NextOrders::GatherInputs). */
class TreesModel final : public AnswerModel {
public:
	TreesModel(std::shared_ptr<const TreeModel> trees, std::function<Inputs(const IdleBuilder&)> gather)
		: trees(std::move(trees)), gather(std::move(gather)) {}

	std::string Name() const override { return trees->Name(); }

	Answers Predict(const IdleBuilder& builder) override
	{
		lastInputs = gather(builder);
		return trees->Predict(lastInputs);
	}

	const Inputs& LastInputs() const { return lastInputs; }

private:
	std::shared_ptr<const TreeModel> trees;
	std::function<Inputs(const IdleBuilder&)> gather;
	Inputs lastInputs;
};

/* What the library knows of a unit type for the inputs. */
struct UnitFacts {
	std::string name;
	std::string kind;  // a builder kind of Model.h
	bool moves = false;
	float buildPower = 0.f;
};

class NextOrders {
public:
	explicit NextOrders(CCircuitAI* circuit) : circuit(circuit), random(std::random_device()())
	{
		const char* value = Engine()->SkirmishAI_OptionValues_getValueByKey(Id(), "builder_orders");
		on = value != nullptr && std::strcmp(value, "model") == 0;
		if (on) {
			LoadModel();  // at the start, while the game loads: reading the trees takes seconds
		}
	}

	/* Called on every frame before the AI handles it: the economy of whole seconds,
	 * as the state export writes it, and the order chosen last, once carried out. */
	void Update(int frame)
	{
		if (!on) {
			return;
		}
		CommitPending();
		for (auto unit = idle.begin(); unit != idle.end();) {  // busy since before this frame
			unit = unit->second.busyFrom >= 0 && unit->second.busyFrom < frame ? idle.erase(unit) : std::next(unit);
		}
		if (frame % ECONOMY_FRAMES == 1) {
			// what the AI reads at the start of a frame is the state at the end of the
			// frame before, the one the export writes a resource line for
			lastSecond = ReadEconomy(frame - 1);
		}
	}

	/* An idle event of one of the team's units: it is idle until it gets an order. */
	void UnitIdle(int unitId)
	{
		if (on) {
			idle[unitId] = {Engine()->Game_getCurrentFrame(Id()), -1};
		}
	}

	bool IsOn() { return on; }

	std::string Decide(CCircuitUnit* unit)
	{
		if (!on || unit == nullptr) {
			return "";
		}
		if (!model) {
			LoadModel();
		}
		CommitPending();
		CCircuitDef* def = unit->GetCircuitDef();
		IdleBuilder builder;
		builder.skirmishAIId = Id();
		builder.teamId = circuit->GetTeamId();
		builder.unitId = unit->GetId();
		builder.unit = def->GetDef()->GetName();
		builder.kind = Kind(def);
		builder.buildPower = def->GetWorkerTime();
		builder.frame = circuit->GetLastFrame();
		const springai::AIFloat3& position = unit->GetPos(builder.frame);
		builder.x = position.x;
		builder.z = position.z;

		const Answers answers = model->Predict(builder);
		const Choice choice = Choose(answers, [&](const std::string& answer) { return CanGive(def, builder.kind, answer); },
			std::uniform_real_distribution<float>(0.f, 1.f)(random));
		std::string line = Describe(builder) + ": " + OutcomeName(choice.outcome);
		if (choice.outcome == Outcome::CHOSEN) {
			line += " " + choice.chosen.name + " " + Rounded(choice.chosen.probability);
		} else if (choice.outcome == Outcome::BELOW_THRESHOLD) {
			line += ", best " + choice.chosen.name + " " + Rounded(choice.chosen.probability);
		}
		line += "; " + std::to_string(choice.candidates) + " of " + std::to_string(choice.possible.size())
			+ " possible of " + std::to_string(answers.size()) + " at 10% or more";
		if (!choice.possible.empty()) {
			line += ":";
			for (std::size_t index = 0; index < choice.possible.size() && index < LOGGED_ANSWERS; ++index) {
				line += " " + choice.possible[index].name + " " + Rounded(choice.possible[index].probability);
			}
		}
		if (choice.outcome != Outcome::CHOSEN) {
			line += "; left to BARb";
		}
		Log(line);
		if (trees != nullptr && decisions++ % INPUTS_LOGGED_EVERY == 0) {
			LogInputs(builder, trees->LastInputs());
		}
		if (choice.outcome == Outcome::CHOSEN) {
			pending = {builder.unitId, choice.chosen.name, builder.frame};  // an order once carried out
		}
		return choice.outcome == Outcome::CHOSEN ? choice.chosen.name : "";
	}

	/* BARb gave `task` to a unit the model did not decide for: an order of the bot
	 * all the same, for the order history. */
	void BarbOrdered(CCircuitUnit* unit, IUnitTask* task)
	{
		if (!on || unit == nullptr) {
			return;
		}
		const std::string answer = AnswerOf(task);
		if (answer.empty()) {
			return;
		}
		CommitPending();
		const int frame = circuit->GetLastFrame();
		Ordered(unit->GetId(), answer, frame);
		IdleBuilder builder;
		builder.unitId = unit->GetId();
		builder.unit = unit->GetCircuitDef()->GetDef()->GetName();
		builder.kind = Kind(unit->GetCircuitDef());
		builder.frame = frame;
		Log(Describe(builder) + ": BARb ordered " + answer);
	}

	/* The start position and its role, found by the script from the usual metal spots
	 * of the map (next_order.as); empty when it has none. */
	void SetStart(const std::string& position, const std::string& role)
	{
		startPosition = position;
		startRole = role;
	}

	void Failed(CCircuitUnit* unit, const std::string& order, const std::string& reason)
	{
		if (unit == nullptr) {
			return;
		}
		if (pending.unitId == unit->GetId()) {
			pending = {};  // never given: no order of the history
		}
		IdleBuilder builder;
		builder.unitId = unit->GetId();
		builder.unit = unit->GetCircuitDef()->GetDef()->GetName();
		builder.kind = Kind(unit->GetCircuitDef());
		builder.frame = circuit->GetLastFrame();
		Log(Describe(builder) + ": cannot carry out " + order + ": " + reason + "; left to BARb");
	}

	IUnitTask* BarbTask(CCircuitUnit* unit, const std::string& what)
	{
		if (unit == nullptr) {
			return nullptr;
		}
		const springai::AIFloat3& position = unit->GetPos(circuit->GetLastFrame());
		CCircuitDef* def = unit->GetCircuitDef();
		circuit::CEconomyManager* economy = circuit->GetEconomyManager();
		circuit::CBuilderManager* builders = circuit->GetBuilderManager();
		if (what == "mex") {
			return economy->UpdateMetalTasks(position, unit);
		}
		if (what == "reclaim" || what == "resurrect") {
			// BARb's reclaim near the builder (CEconomyManager::UpdateReclaimTasks with
			// isNear): the nearest reachable, safe feature within 20 to 60 s of its travel
			return economy->UpdateReclaimTasks(position, unit, true);
		}
		if (what == "repair") {
			// the nearest of BARb's repair tasks this builder can take
			IBuilderTask* nearest = nullptr;
			float nearestDistance = 0.f;
			for (IBuilderTask* task : builders->GetTasks(IBuilderTask::BuildType::REPAIR)) {
				if (!task->CanAssignTo(unit)) {
					continue;
				}
				const float distance = position.SqDistance2D(task->GetPosition());
				if (nearest == nullptr || distance < nearestDistance) {
					nearest = task;
					nearestDistance = distance;
				}
			}
			return nearest;
		}
		if (what == "assist") {
			// as BARb assists when idle: a factory that wants help, else guard the
			// closest factory (CEconomyManager::CheckMobileAssistRequired,
			// CBuilderManager::CreateBuilderTask)
			if (def->IsMobile()) {
				IBuilderTask* task = economy->CheckMobileAssistRequired(position, unit);
				if (task != nullptr) {
					return task;
				}
			}
			CCircuitUnit* factory = circuit->GetFactoryManager()->GetClosestFactory(position);
			if (factory == nullptr) {
				return nullptr;
			}
			if (!def->IsMobile()) {
				const float reach = def->GetBuildDistance() + factory->GetCircuitDef()->GetRadius();
				if (position.SqDistance2D(factory->GetPos(circuit->GetLastFrame())) > reach * reach) {
					return nullptr;  // a tower assists only what it reaches
				}
			}
			return builders->EnqueueB(circuit::TaskB::Guard(IBuilderTask::Priority::NORMAL, factory, true,
				FRAMES_PER_SEC * 60));
		}
		return nullptr;
	}

	bool SpotOpen(int spot)
	{
		circuit::CMetalManager* metal = circuit->GetMetalManager();
		return spot >= 0 && spot < static_cast<int>(metal->GetSpots().size()) && metal->IsOpenSpot(spot);
	}

private:
	int Id() const { return circuit->GetSkirmishAIId(); }

	const SSkirmishAICallback* Engine() const { return EngineCallback(Id()); }

	void Log(const std::string& text) const
	{
		const std::string line = "Reason8 next order: team " + std::to_string(circuit->GetTeamId()) + ": " + text;
		Engine()->Log_log(Id(), line.c_str());
	}

	std::string Describe(const IdleBuilder& builder) const
	{
		return "frame " + std::to_string(builder.frame) + ": " + builder.unit + " " + std::to_string(builder.unitId)
			+ " " + builder.kind;
	}

	void LoadModel()
	{
		const char* folderValue = Engine()->SkirmishAI_Info_getValueByKey(Id(), SKIRMISH_AI_PROPERTY_DATA_DIR);
		const std::string folder = folderValue == nullptr ? "." : folderValue;
		const std::string modelPath = folder + "/" + MODEL_FILE;
		std::string why = std::string("no learned model in ") + MODEL_FILE;
		if (std::ifstream(modelPath).is_open()) {
			std::string error;
			bool loaded = false;
			const auto start = std::chrono::steady_clock::now();
			std::shared_ptr<const TreeModel> found = TreeModel::Shared(modelPath, error, loaded);
			const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
			if (found) {
				UseTrees(found);
				Log("model " + found->Name() + " (the learned trees) from " + MODEL_FILE + ": "
					+ std::to_string(found->Trees()) + " trees, " + std::to_string(found->Nodes()) + " nodes, "
					+ std::to_string(found->Features().size()) + " inputs, "
					+ (loaded ? "read in " + Number(seconds) + " s, " + Number(found->Bytes() / 1e6) + " MB"
					          : "shared with an AI of this process")
					+ "; " + SkillText());
				return;
			}
			why = std::string("cannot read ") + MODEL_FILE + ": " + error;
		}
		auto standIn = std::make_unique<StandInModel>();
		const std::string path = folder + "/" + STAND_IN_FILE;
		std::ifstream file(path);
		const bool found = file.is_open();
		const int rows = found ? standIn->Load(file) : 0;
		Log("model " + standIn->Name() + " (NOT the learned model: a fixed answer per builder unit and minute; "
			+ why + "), " + std::to_string(rows) + " rows for " + std::to_string(standIn->Units())
			+ " builder units from " + STAND_IN_FILE + (found ? "" : ", which is missing: every order is left to BARb"));
		model = std::move(standIn);
	}

	void UseTrees(const std::shared_ptr<const TreeModel>& loaded)
	{
		treeModel = loaded;
		for (const TreeModel::Feature& feature : loaded->Features()) {
			const std::string prefix = "own_done_";
			if (feature.name.compare(0, prefix.size(), prefix) == 0) {
				types.insert(feature.name.substr(prefix.size()));
			}
		}
		hasSkill = loaded->HasFeature("skill");
		const char* option = Engine()->SkirmishAI_OptionValues_getValueByKey(Id(), "skill");
		char* end = nullptr;
		const double chosen = option == nullptr ? 0.0 : std::strtod(option, &end);
		if (option != nullptr && *option != '\0' && end != nullptr && *end == '\0' && std::isfinite(chosen)) {
			skill = chosen;
			skillSource = "the AI option skill";
		} else {
			const auto quantile = loaded->SkillQuantiles().find(DEFAULT_SKILL_QUANTILE);
			if (quantile != loaded->SkillQuantiles().end()) {
				skill = quantile->second;
				skillSource = std::string("the ") + DEFAULT_SKILL_QUANTILE + " quantile of training";
			}
		}
		auto learned = std::make_unique<TreesModel>(loaded, [this](const IdleBuilder& builder) { return GatherInputs(builder); });
		trees = learned.get();
		model = std::move(learned);
	}

	std::string SkillText() const
	{
		if (!hasSkill) {
			return "skill is no input of this model";
		}
		if (std::isnan(skill)) {
			return "skill missing";
		}
		return "skill " + Number(skill) + " (" + skillSource + ")";
	}

	/* A model order, once the script did not report it failed, or BARb's: an order
	 * of the history, after which the unit is busy. */
	void CommitPending()
	{
		if (pending.unitId >= 0) {
			Ordered(pending.unitId, pending.answer, pending.frame);
			pending = {};
		}
	}

	void Ordered(int unitId, const std::string& answer, int frame)
	{
		history.Record(unitId, answer, frame);
		const auto unit = idle.find(unitId);
		if (unit != idle.end() && unit->second.busyFrom < 0) {
			unit->second.busyFrom = frame;
		}
	}

	/* Whether a unit was idle at the end of the frame before `frame`, as the table
	 * reads the state: it went idle before then and got no order before then. */
	bool IdleBefore(int unitId, int frame) const
	{
		const auto unit = idle.find(unitId);
		return unit != idle.end() && unit->second.since < frame
			&& (unit->second.busyFrom < 0 || unit->second.busyFrom >= frame);
	}

	/* The answer an order of BARb's gives, as the decision table names it: the unit it
	 * builds, or the job it does; "" for none (waiting, fighting, patrolling). */
	static std::string AnswerOf(IUnitTask* task)
	{
		auto* builderTask = dynamic_cast<IBuilderTask*>(task);
		if (builderTask == nullptr) {
			return "";
		}
		switch (builderTask->GetBuildType()) {
			case IBuilderTask::BuildType::REPAIR: return "repair";
			case IBuilderTask::BuildType::RECLAIM: return "reclaim";
			case IBuilderTask::BuildType::RESURRECT: return "resurrect";
			case IBuilderTask::BuildType::GUARD: return "assist";
			case IBuilderTask::BuildType::PATROL:
			case IBuilderTask::BuildType::COMBAT:
			case IBuilderTask::BuildType::WAIT:
			case IBuilderTask::BuildType::TERRAFORM: return "";
			default: break;
		}
		CCircuitDef* built = builderTask->GetBuildDef();
		return built == nullptr ? "" : built->GetDef()->GetName();
	}

	Economy ReadEconomy(int frame)
	{
		Economy economy;
		economy.frame = frame;
		const SSkirmishAICallback* engine = Engine();
		const int resources[2] = {engine->getResourceByName(Id(), "Metal"), engine->getResourceByName(Id(), "Energy")};
		for (int resource = 0; resource < 2; ++resource) {
			const int id = resources[resource];
			if (id < 0) {
				return Economy();
			}
			const double read[4] = {engine->Economy_getCurrent(Id(), id), engine->Economy_getStorage(Id(), id),
				engine->Economy_getIncome(Id(), id), engine->Economy_getUsage(Id(), id)};
			for (int value = 0; value < 4; ++value) {
				const int index = resource * 4 + value;
				economy.values[index] = ExportRounded(read[value], Economy::Decimals()[index]);
			}
		}
		return economy;
	}

	const UnitFacts& FactsOf(int defId)
	{
		auto found = unitFacts.find(defId);
		if (found != unitFacts.end()) {
			return found->second;
		}
		UnitFacts facts;
		const SSkirmishAICallback* engine = Engine();
		const char* name = engine->UnitDef_getName(Id(), defId);
		facts.name = name == nullptr ? "" : name;
		facts.moves = engine->UnitDef_getSpeed(Id(), defId) > 0.f;
		facts.buildPower = engine->UnitDef_getBuildSpeed(Id(), defId);
		CCircuitDef* def = circuit->GetCircuitDef(defId);
		facts.kind = def == nullptr ? OTHER_BUILDER : Kind(def);
		return unitFacts.emplace(defId, facts).first->second;
	}

	/* Every input of the model for the builder the order is for, as the decision
	 * table defines it (docs/reference/builder-model.md, "The inputs"). */
	Inputs GatherInputs(const IdleBuilder& builder)
	{
		const SSkirmishAICallback* engine = Engine();
		Inputs inputs;
		std::vector<int> units(MAX_TEAM_UNITS);
		const int count = std::min(engine->getTeamUnits(Id(), units.data(), MAX_TEAM_UNITS), MAX_TEAM_UNITS);

		// the order history
		if (faction.empty()) {
			for (int index = 0; index < count && faction.empty(); ++index) {
				const int defId = engine->Unit_getDef(Id(), units[index]);
				if (defId >= 0 && FactsOf(defId).kind == COMMANDER) {
					faction = FactionOf(FactsOf(defId).name);
				}
			}
		}
		if (!faction.empty()) {
			inputs.Set("faction", faction);
		}
		const char* mapName = engine->Map_getName(Id());
		if (mapName != nullptr) {
			inputs.Set("map", mapName);
		}
		if (!startPosition.empty()) {
			inputs.Set("position", startPosition);
		}
		if (!startRole.empty()) {
			inputs.Set("role", startRole);
		}
		history.Fill(inputs, builder.unitId, types);

		// the builder
		const int builderDef = engine->Unit_getDef(Id(), builder.unitId);
		inputs.Set("builder_kind", builder.kind);
		inputs.Set("builder_role", UnitType(builder.unit));
		if (builderDef >= 0) {
			inputs.Set("builder_moves", FactsOf(builderDef).moves ? 1 : 0);
			inputs.Set("builder_build_power", FactsOf(builderDef).buildPower);
		}

		// time, and the economy of the last whole second before the order
		inputs.Set("time_s", builder.frame / 30.0);
		if (lastSecond.frame >= 0) {
			for (int index = 0; index < Economy::SIZE; ++index) {
				inputs.Set(Economy::Names()[index], lastSecond.values[index]);
			}
		}

		// own units, and build power: all finished builders' and the idle ones'
		std::map<std::string, int> done, building;
		for (const std::string& type : types) {
			done[type] = 0;
			building[type] = 0;
		}
		std::map<std::string, double> teamPower, idlePower;
		for (const char* kind : {COMMANDER, FACTORY, CONSTRUCTION, TOWER, OTHER_BUILDER}) {
			teamPower[kind] = 0.0;
			idlePower[kind] = 0.0;
		}
		double teamTotal = 0.0, idleTotal = 0.0;
		for (int index = 0; index < count; ++index) {
			const int defId = engine->Unit_getDef(Id(), units[index]);
			if (defId < 0) {
				continue;
			}
			const UnitFacts& facts = FactsOf(defId);
			const std::string type = TypeOf(facts.name, types);
			if (engine->Unit_isBeingBuilt(Id(), units[index])) {
				++building[type];
				continue;
			}
			++done[type];
			if (facts.buildPower > 0.f) {
				teamPower[facts.kind] += facts.buildPower;
				teamTotal += facts.buildPower;
				if (IdleBefore(units[index], builder.frame)) {
					idlePower[facts.kind] += facts.buildPower;
					idleTotal += facts.buildPower;
				}
			}
		}
		for (const std::string& type : types) {
			inputs.Set("own_done_" + type, done[type]);
			inputs.Set("own_building_" + type, building[type]);
		}
		inputs.Set("team_build_power", teamTotal);
		inputs.Set("idle_build_power", idleTotal);
		for (const auto& [kind, power] : teamPower) {
			inputs.Set("team_build_power_" + kind, power);
			inputs.Set("idle_build_power_" + kind, idlePower[kind]);
		}

		if (hasSkill && !std::isnan(skill)) {
			inputs.Set("skill", skill);
		}
		return inputs;
	}

	/* One line with the inputs of a decision as the model got them: every name, and
	 * every number but zero, by the model's inputs; "?" for a missing one. */
	void LogInputs(const IdleBuilder& builder, const Inputs& inputs)
	{
		std::string line = Describe(builder) + ": inputs";
		const char* separator = " ";
		for (const TreeModel::Feature& feature : treeModel->Features()) {
			std::string value;
			if (feature.categorical) {
				const std::string* name = inputs.Name(feature.name);
				value = name == nullptr ? "?" : *name;
			} else {
				const double* number = inputs.Number(feature.name);
				if (number != nullptr && *number == 0.0) {
					continue;
				}
				value = number == nullptr ? "?" : Number(*number);
			}
			line += separator + feature.name + "=" + value;
			separator = "; ";
		}
		Log(line);
	}

	/* The kind of a builder, as reason8/context/builders.py tells it from the unit files. */
	static std::string Kind(const CCircuitDef* def)
	{
		if (def->IsRoleComm()) {
			return COMMANDER;
		}
		const bool lists = !def->GetBuildOptions().empty();
		if (!def->IsMobile()) {
			return lists ? FACTORY : TOWER;
		}
		return lists ? CONSTRUCTION : OTHER_BUILDER;
	}

	/* Whether the builder can ever give `answer`: a unit of its build list, or a job
	 * its unit definition allows. Factories take no jobs. What the team cannot afford
	 * stays possible (ADR 0019). */
	bool CanGive(const CCircuitDef* def, const std::string& kind, const std::string& answer) const
	{
		if (IsJob(answer)) {
			if (kind == FACTORY) {
				return false;
			}
			if (answer == "assist") return def->IsAbleToAssist();
			if (answer == "reclaim") return def->IsAbleToReclaim();
			if (answer == "repair") return def->IsAbleToRepair();
			return def->IsAbleToResurrect();
		}
		CCircuitDef* built = circuit->GetCircuitDef(answer.c_str());
		return built != nullptr && def->CanBuild(built);
	}

	struct Idle {
		int since;      // the frame of its idle event
		int busyFrom;   // the frame of the first order since, -1 for none
	};

	struct Pending {
		int unitId = -1;
		std::string answer;
		int frame = 0;
	};

	CCircuitAI* circuit;
	bool on = false;
	std::unique_ptr<AnswerModel> model;
	std::mt19937 random;

	// the learned model, when it is the one that answers
	std::shared_ptr<const TreeModel> treeModel;
	TreesModel* trees = nullptr;  // owned by `model`
	std::set<std::string> types;  // the unit types of own_done_<type>
	bool hasSkill = false;
	double skill = std::numeric_limits<double>::quiet_NaN();
	std::string skillSource;
	int decisions = 0;

	// what the inputs need to remember
	OrderHistory history;
	Pending pending;  // the model's last order, until the script reports it failed or it is given
	std::unordered_map<int, Idle> idle;  // units by their last idle event, until a frame after an order
	Economy lastSecond;  // the economy at the end of the last whole second's frame
	std::unordered_map<int, UnitFacts> unitFacts;  // by unit def
	std::string faction;
	std::string startPosition;
	std::string startRole;
};

std::unordered_map<int, std::unique_ptr<NextOrders>> nextOrders;

}  // namespace

void NextOrderUpdate(int skirmishAIId, int frame)
{
	const auto found = nextOrders.find(skirmishAIId);
	if (found != nextOrders.end()) {
		found->second->Update(frame);
	}
}

void NextOrderUnitIdle(int skirmishAIId, int unitId)
{
	const auto found = nextOrders.find(skirmishAIId);
	if (found != nextOrders.end()) {
		found->second->UnitIdle(unitId);
	}
}

void RegisterNextOrder(asIScriptEngine* engine, CCircuitAI* circuit)
{
	std::unique_ptr<NextOrders>& orders = nextOrders[circuit->GetSkirmishAIId()];
	orders = std::make_unique<NextOrders>(circuit);
	NextOrders* object = orders.get();
	int result = engine->RegisterGlobalFunction("bool Reason8ModelOrders()", asMETHOD(NextOrders, IsOn), asCALL_THISCALL_ASGLOBAL, object);
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("string Reason8NextOrder(CCircuitUnit@)", asMETHOD(NextOrders, Decide), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("void Reason8OrderFailed(CCircuitUnit@, const string& in, const string& in)", asMETHOD(NextOrders, Failed), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("IUnitTask@+ Reason8BarbTask(CCircuitUnit@, const string& in)", asMETHOD(NextOrders, BarbTask), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("bool Reason8SpotOpen(int)", asMETHOD(NextOrders, SpotOpen), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("void Reason8BarbOrdered(CCircuitUnit@, IUnitTask@)", asMETHOD(NextOrders, BarbOrdered), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result >= 0) {
		result = engine->RegisterGlobalFunction("void Reason8SetStart(const string& in, const string& in)", asMETHOD(NextOrders, SetStart), asCALL_THISCALL_ASGLOBAL, object);
	}
	if (result < 0) {
		throw std::runtime_error("Reason8: cannot register the next order for the scripts");
	}
}

}  // namespace reason8
