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
 *       consults the model (Model.h) about the idle builder, masks and
 *       chooses (Choice.h), logs the decision, and returns the order chosen:
 *       a unit name, or a job (assist, reclaim, repair, resurrect); "" when
 *       it is left to BARb
 *   void Reason8OrderFailed(CCircuitUnit@ builder, const string& in order,
 *                           const string& in reason)
 *       logs that the order chosen cannot be carried out: it is left to BARb
 *   IUnitTask@ Reason8BarbTask(CCircuitUnit@ builder, const string& in what)
 *       BARb's own task for `what`, with BARb's own choice of place or
 *       target: "mex" (BARb's next metal spot), "assist", "reclaim",
 *       "repair" or "resurrect"; null when BARb has none
 *   bool Reason8SpotOpen(int spot)
 *       whether BARb's metal spot `spot` has no extractor on it
 *   void Reason8BarbOrdered(CCircuitUnit@ builder, IUnitTask@ task)
 *       BARb gave the builder `task`: an order of the bot for the model's
 *       order history all the same
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
