/* Reason8 command governor: counts, and optionally caps, every unit command
 * a CircuitAI (BARb) build sends, the way docs/research/apm.md counts a
 * player's actions. GPL-2.0-or-later. */

#ifndef REASON8_GOVERNOR_H
#define REASON8_GOVERNOR_H

struct SSkirmishAICallback;

namespace reason8 {

/* Returns the callback the AI should use instead of `inner`: a copy whose
 * Engine_handleCommand goes through the governor. The mode comes from the
 * environment variable REASON8_GOVERNOR: "off" (default; returns `inner`),
 * "count" (log only) or "cap" (drop commands that would exceed the budget of
 * the 30-40 skill band in ADR 0008). */
const SSkirmishAICallback* InstallGovernor(int skirmishAIId, const SSkirmishAICallback* inner);

/* Logs the last minute and the totals, and frees the governor's state. */
void ReleaseGovernor(int skirmishAIId);

}  // namespace reason8

#endif  // REASON8_GOVERNOR_H
