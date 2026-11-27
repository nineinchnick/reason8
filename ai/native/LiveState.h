/* Reason8 live state: what the game looks like now, for BARb's AngelScript
 * scripts, read from the engine when a script asks. GPL-2.0-or-later. */

#ifndef REASON8_LIVE_STATE_H
#define REASON8_LIVE_STATE_H

class asIScriptEngine;

namespace reason8 {

/* Registers, for the scripts of one AI, the global functions
 *
 *   float Reason8CurrentWind()       the wind's strength now
 *   float Reason8Resource(const string& in resource, const string& in what)
 *                                    resource "metal" or "energy"; what
 *                                    "current" (stored), "storage", "income",
 *                                    "expense" or "pull"; -1 when unknown
 *   int Reason8UnitCount(const string& in unitName)
 *                                    the team's finished units of that name
 *   string Reason8Standing()         every finished unit of the team, counted
 *                                    by name: "armmex 3, armwin 4"
 *
 * The values are the engine's, the same that Spring.GetWind and
 * Spring.GetTeamResources give a widget. */
void RegisterLiveState(asIScriptEngine* engine, int skirmishAIId);

}  // namespace reason8

#endif  // REASON8_LIVE_STATE_H
