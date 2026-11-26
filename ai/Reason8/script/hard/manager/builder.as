// Reason8: a copy of BARb's script/hard/manager/builder.as (Beyond All Reason,
// luarules/configs/BARb/stable) with hooks for the Reason8 opening. Every
// change is marked "Reason8:". reason8/bot/build.py refuses to build when the
// stock file differs from the one this copy was made from (see ../../../base.json).
#include "../../unit.as"
#include "../reason8/opening.as"  // Reason8:


namespace Builder {

CCircuitUnit@ energizer1 = null;
CCircuitUnit@ energizer2 = null;

IUnitTask@ AiMakeTask(CCircuitUnit@ unit)
{
	// Reason8: an idle builder waits as long as a player takes to notice it
	const int reactionFrames = Reason8::ReactionWait(unit, false);
	if (reactionFrames > 0)
		return aiBuilderMgr.Enqueue(TaskB::Wait(reactionFrames));

	// Reason8: the commander plays the opening first
	IUnitTask@ task = Reason8::MakeCommanderTask(unit);
	if (task is null)
		@task = aiBuilderMgr.DefaultMakeTask(unit);
	Reason8::TaskGiven(unit, task, false);  // Reason8:
	return task;
}

void AiTaskAdded(IUnitTask@ task)
{
}

void AiTaskRemoved(IUnitTask@ task, bool done)
{
	Reason8::CommanderTaskRemoved(task, done);  // Reason8:
	Reason8::TaskEnded(task, done);  // Reason8:
}

void AiUnitAdded(CCircuitUnit@ unit, Unit::UseAs usage)
{
	const CCircuitDef@ cdef = unit.circuitDef;
	if (usage != Unit::UseAs::BUILDER || cdef.IsRoleAny(Unit::Role::COMM.mask))
		return;

	// constructor with BASE attribute is assigned to tasks near base
	if (cdef.costM < 200.f) {
		if (energizer1 is null
			&& (uint(cdef.count) > aiMilitaryMgr.GetGuardTaskNum() || cdef.IsAbleToFly()))
		{
			@energizer1 = unit;
			unit.AddAttribute(Unit::Attr::BASE.type);
		}
	} else {
		if (energizer2 is null) {
			@energizer2 = unit;
			unit.AddAttribute(Unit::Attr::BASE.type);
		}
	}
}

void AiUnitRemoved(CCircuitUnit@ unit, Unit::UseAs usage)
{
	if (energizer1 is unit)
		@energizer1 = null;
	else if (energizer2 is unit)
		@energizer2 = null;
}

void AiLoad(IStream& istream)
{
	Id e1id = -1, e2id = -1;
	istream >> e1id >> e2id;
	@energizer1 = ai.GetTeamUnit(e1id);
	@energizer2 = ai.GetTeamUnit(e2id);
	if (energizer1 !is null)
		energizer1.AddAttribute(Unit::Attr::BASE.type);
	if (energizer2 !is null)
		energizer2.AddAttribute(Unit::Attr::BASE.type);
}

void AiSave(OStream& ostream)
{
	ostream << Id(energizer1 !is null ? energizer1.id : -1)
			<< Id(energizer2 !is null ? energizer2.id : -1);
}

}  // namespace Builder
