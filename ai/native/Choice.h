/* Reason8 choice: what the bot does with a model's answer for the next order
 * of an idle builder (ADR 0019), without the engine. GPL-2.0-or-later.
 *
 * The model gives a probability per answer: a unit to build, or a job without
 * a target (assist, reclaim, repair, resurrect). The answers the builder can
 * never carry out are removed and the rest rescaled to sum to one (the mask);
 * the bot then samples among the answers of at least CHOICE_THRESHOLD, in
 * proportion to their probabilities. When none reaches it, the order is left
 * to BARb. */

#ifndef REASON8_CHOICE_H
#define REASON8_CHOICE_H

#include <algorithm>
#include <functional>
#include <string>
#include <vector>

namespace reason8 {

/* The jobs a builder can be given without a target, as the decision table
 * names them (reason8/context/builders.py, JOBS). */
inline const std::vector<std::string>& Jobs()
{
	static const std::vector<std::string> jobs = {"assist", "reclaim", "repair", "resurrect"};
	return jobs;
}

inline bool IsJob(const std::string& answer)
{
	const std::vector<std::string>& jobs = Jobs();
	return std::find(jobs.begin(), jobs.end(), answer) != jobs.end();
}

struct Answer {
	std::string name;  // a unit name or a job
	float probability;
};
using Answers = std::vector<Answer>;

/* ADR 0019: the bot samples only among answers at least this likely. */
constexpr float CHOICE_THRESHOLD = 0.10f;

enum class Outcome {
	CHOSEN,            // an answer was drawn
	BELOW_THRESHOLD,   // no possible answer reached the threshold: left to BARb
	NOTHING_POSSIBLE,  // the mask removed every answer: left to BARb
	NO_ANSWERS,        // the model had no answer for this builder: left to BARb
};

inline const char* OutcomeName(Outcome outcome)
{
	switch (outcome) {
		case Outcome::CHOSEN: return "model chose";
		case Outcome::BELOW_THRESHOLD: return "below threshold";
		case Outcome::NOTHING_POSSIBLE: return "nothing possible";
		case Outcome::NO_ANSWERS: return "no answers";
	}
	return "?";
}

struct Choice {
	Outcome outcome = Outcome::NO_ANSWERS;
	Answer chosen = {"", 0.f};  // CHOSEN: the answer drawn; BELOW_THRESHOLD: the most likely one
	Answers possible;           // after the mask, rescaled, most likely first
	int candidates = 0;         // possible answers at or above the threshold
};

/* `answers` without those `canGive` rejects and without zeros, rescaled to sum
 * to one, most likely first (ties keep their order). Empty when nothing is
 * left. */
inline Answers Mask(const Answers& answers, const std::function<bool(const std::string&)>& canGive)
{
	Answers kept;
	float total = 0.f;
	for (const Answer& answer : answers) {
		if (answer.probability > 0.f && canGive(answer.name)) {
			kept.push_back(answer);
			total += answer.probability;
		}
	}
	if (total <= 0.f) {
		return {};
	}
	for (Answer& answer : kept) {
		answer.probability /= total;
	}
	std::stable_sort(kept.begin(), kept.end(),
		[](const Answer& a, const Answer& b) { return a.probability > b.probability; });
	return kept;
}

/* The choice for one idle builder. `uniform` is a random number in [0, 1). */
inline Choice Choose(const Answers& answers, const std::function<bool(const std::string&)>& canGive,
		float uniform, float threshold = CHOICE_THRESHOLD)
{
	Choice choice;
	if (answers.empty()) {
		return choice;
	}
	choice.possible = Mask(answers, canGive);
	if (choice.possible.empty()) {
		choice.outcome = Outcome::NOTHING_POSSIBLE;
		return choice;
	}
	float total = 0.f;
	for (const Answer& answer : choice.possible) {
		if (answer.probability >= threshold) {
			total += answer.probability;
			++choice.candidates;
		}
	}
	if (choice.candidates == 0) {
		choice.outcome = Outcome::BELOW_THRESHOLD;
		choice.chosen = choice.possible.front();
		return choice;
	}
	choice.outcome = Outcome::CHOSEN;
	const float target = std::clamp(uniform, 0.f, 1.f) * total;
	float sum = 0.f;
	for (const Answer& answer : choice.possible) {
		if (answer.probability < threshold) {
			continue;
		}
		choice.chosen = answer;  // the last candidate when rounding leaves `target` past the sum
		sum += answer.probability;
		if (target < sum) {
			break;
		}
	}
	return choice;
}

}  // namespace reason8

#endif  // REASON8_CHOICE_H
