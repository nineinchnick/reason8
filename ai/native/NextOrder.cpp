/* Reason8 next order; see NextOrder.h. GPL-2.0-or-later. */

#include "NextOrder.h"

#include "Choice.h"
#include "Governor.h"
#include "Model.h"
#include "StandIn.h"

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

#include <cstring>
#include <fstream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace reason8 {

namespace {

using circuit::CCircuitAI;
using circuit::CCircuitDef;
using circuit::CCircuitUnit;
using circuit::IBuilderTask;
using circuit::IUnitTask;

/* The stand-in's table in the AI's folder, written by `reason8 bot build`. */
const char* const STAND_IN_FILE = "reason8/stand_in.txt";
/* Answers listed in a decision's log line. */
constexpr std::size_t LOGGED_ANSWERS = 5;

std::string Rounded(float probability)
{
	char text[16];
	std::snprintf(text, sizeof(text), "%.2f", probability);
	return text;
}

class NextOrders {
public:
	explicit NextOrders(CCircuitAI* circuit) : circuit(circuit), random(std::random_device()())
	{
		const char* value = Engine()->SkirmishAI_OptionValues_getValueByKey(Id(), "builder_orders");
		on = value != nullptr && std::strcmp(value, "model") == 0;
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
		return choice.outcome == Outcome::CHOSEN ? choice.chosen.name : "";
	}

	void Failed(CCircuitUnit* unit, const std::string& order, const std::string& reason)
	{
		if (unit == nullptr) {
			return;
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
		auto standIn = std::make_unique<StandInModel>();
		const char* folder = Engine()->SkirmishAI_Info_getValueByKey(Id(), SKIRMISH_AI_PROPERTY_DATA_DIR);
		const std::string path = std::string(folder == nullptr ? "." : folder) + "/" + STAND_IN_FILE;
		std::ifstream file(path);
		const bool found = file.is_open();
		const int rows = found ? standIn->Load(file) : 0;
		Log("model " + standIn->Name() + " (NOT the learned model: a fixed answer per builder unit and minute), "
			+ std::to_string(rows) + " rows for " + std::to_string(standIn->Units()) + " builder units from "
			+ STAND_IN_FILE + (found ? "" : ", which is missing: every order is left to BARb"));
		model = std::move(standIn);
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

	CCircuitAI* circuit;
	bool on = false;
	std::unique_ptr<AnswerModel> model;
	std::mt19937 random;
};

std::unordered_map<int, std::unique_ptr<NextOrders>> nextOrders;

}  // namespace

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
	if (result < 0) {
		throw std::runtime_error("Reason8: cannot register the next order for the scripts");
	}
}

}  // namespace reason8
