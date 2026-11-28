/* Reason8 next order: the bot, as one player, decides the next order for a
 * builder that has nothing to do, as a person notices an idle builder and
 * gives it something to do (ADR 0019). For BARb's AngelScript scripts.
 * GPL-2.0-or-later. */

#ifndef REASON8_NEXT_ORDER_H
#define REASON8_NEXT_ORDER_H

class asIScriptEngine;
namespace circuit {
class CCircuitAI;
}

namespace reason8 {

/* Registers, for the scripts of one AI, the global functions
 *
 *   bool Reason8ModelOrders()
 *       whether the AI option builder_orders is "model": during the opening
 *       the model decides the next order for each idle builder, instead of
 *       the opening table being played
 *   string Reason8NextOrder(CCircuitUnit@ builder)
 *       consults the model (Model.h) about the idle builder, masks, holds
 *       back the answers it could not carry out lately and chooses
 *       (Choice.h, OrderBook.h), logs the decision, and returns the order
 *       chosen: a unit name, or a job (assist, reclaim, repair, resurrect);
 *       "" when it is left to BARb. The order enters the order history once
 *       it is carried out
 *   void Reason8OrderFailed(CCircuitUnit@ builder, const string& in order,
 *                           const string& in reason)
 *       logs that the order chosen cannot be given: it is left to BARb, and
 *       held back for the builder for a while
 *   bool Reason8OrderEnded(int builder, const string& in order, bool done,
 *                          int lastedFrames)
 *       logs the end of a model order's task; true when it ended at once:
 *       not carried out, held back for the builder, left to BARb
 *   IUnitTask@ Reason8TaskInProgress(CCircuitUnit@ builder)
 *       the builder's task when BARb reevaluates it, null when it is idle
 *   IUnitTask@ Reason8HelpBuild(CCircuitUnit@ builder, const string& in unit)
 *       the task building a structure `unit` that the team has under
 *       construction (a factory anywhere, another one near the builder),
 *       for the builder to help; null when there is none
 *   IUnitTask@ Reason8BarbTask(CCircuitUnit@ builder, const string& in what)
 *       a task for the job `what` ("assist", "reclaim", "repair" or
 *       "resurrect") with the target BARb's own tasks choose for it; null
 *       when there is none
 *   IUnitTask@ Reason8BarbSpotTask(CCircuitUnit@ builder,
 *                                  const string& in unit, int& out spot)
 *       an extractor `unit` on the free metal spot BARb would take for its
 *       own next one; null when there is none
 *   bool Reason8SpotOpen(int spot)
 *       whether BARb's metal spot `spot` has no extractor on it
 *   bool Reason8SpotUsable(int spot)
 *       whether it has none and is not in an ally's area
 *   void Reason8BarbOrdered(CCircuitUnit@ builder, IUnitTask@ task)
 *       BARb gave the builder `task`: an order of the bot for the model's
 *       order history all the same, unless the builder keeps the task it is
 *       on
 *   void Reason8SetStart(const string& in position, const string& in role)
 *       the team's start position and its role, for the model's inputs
 *
 * The model is the learned one (Trees.h), read from reason8/builder_model.json
 * in the AI's folder when the AI starts, its inputs computed from the game as
 * the decision table defines them; without that file, the stand-in of
 * StandIn.h, read from reason8/stand_in.txt. Every line goes to the engine log
 * with the prefix "Reason8 next order: team <id>: ". */
void RegisterNextOrder(asIScriptEngine* engine, circuit::CCircuitAI* circuit);

/* Called on every frame of an AI before it handles it: the economy the model's
 * inputs read is that of the last whole second, as the state export has it. */
void NextOrderUpdate(int skirmishAIId, int frame);

/* Called with every idle event of an AI's own units: the idle build power of
 * the model's inputs. */
void NextOrderUnitIdle(int skirmishAIId, int unitId);

}  // namespace reason8

#endif  // REASON8_NEXT_ORDER_H
