/* Reason8 command governor: keeps every unit command a CircuitAI (BARb) build
 * sends within the action budget of ADR 0008, holding back what does not fit
 * and sending it later in order (Budget.h). GPL-2.0-or-later. */

#ifndef REASON8_GOVERNOR_H
#define REASON8_GOVERNOR_H

struct SSkirmishAICallback;

namespace reason8 {

/* Returns the callback the AI should use instead of `inner`: a copy whose
 * Engine_handleCommand goes through the governor. The AI option
 * `command_budget` sets the mode: "defer" (the default: hold commands over
 * the 30-40 band's budget and send them later), "count" (log only) or "off"
 * (returns `inner`). Also logs the engine the library was built for and the
 * one it runs in. */
const SSkirmishAICallback* InstallGovernor(int skirmishAIId, const SSkirmishAICallback* inner);

/* Sends the held commands that fit at `frame`. Called on every update event,
 * before the AI handles it. */
void UpdateGovernor(int skirmishAIId, int frame);

/* Logs the last minute and the totals, and frees the governor's state. */
void ReleaseGovernor(int skirmishAIId);

/* The engine's own callback of an AI, without the governor; nullptr before
 * InstallGovernor. */
const SSkirmishAICallback* EngineCallback(int skirmishAIId);

}  // namespace reason8

#endif  // REASON8_GOVERNOR_H
