/* Reason8 model interface: the next order for a builder with nothing to do
 * (ADR 0019). GPL-2.0-or-later.
 *
 * During the opening the bot, as one player, consults one model, which sees
 * the team's whole state, about each idle builder, and passes its answer to
 * the choice (Choice.h). Any model fits behind this interface: the stand-in
 * of StandIn.h now, the learned one later. */

#ifndef REASON8_MODEL_H
#define REASON8_MODEL_H

#include "Choice.h"

#include <string>

namespace reason8 {

/* The kinds of builders, as the decision table names them
 * (reason8/context/builders.py, BUILDER_KINDS). */
inline const char* const COMMANDER = "commander";
inline const char* const FACTORY = "factory";
inline const char* const CONSTRUCTION = "construction";
inline const char* const TOWER = "tower";
inline const char* const OTHER_BUILDER = "other";

/* The idle builder the next order is for. A model reads whatever else it
 * needs (the team's economy, its units, the map) from the engine through
 * `skirmishAIId`. */
struct IdleBuilder {
	int skirmishAIId = -1;
	int teamId = -1;
	int unitId = -1;
	std::string unit;  // its unit name
	std::string kind;  // one of the kinds above
	float buildPower = 0.f;
	int frame = 0;
	float x = 0.f;  // where it stands
	float z = 0.f;
};

/* A model: a probability per answer for the builder the order is for. An answer is a
 * unit name or a job (Jobs()). The probabilities need not sum to one, and may
 * include answers the builder cannot give: the mask removes them. */
class AnswerModel {
public:
	virtual ~AnswerModel() = default;
	virtual std::string Name() const = 0;
	virtual Answers Predict(const IdleBuilder& builder) = 0;
};

}  // namespace reason8

#endif  // REASON8_MODEL_H
