/* Reason8 builder model: the trees of ADR 0019, read from their file
 * (format reason8.builder-trees/1, docs/reference/builder-model.md) and
 * evaluated without XGBoost. GPL-2.0-or-later.
 *
 * A decision, as the reference evaluator reason8/models/trees.py makes it:
 *
 *   1. encode each input of the file's `features` as a 32-bit float: a number
 *      as it is, a name as the index of its category; a name not among the
 *      categories and an input not given are missing (NaN);
 *   2. each class starts at its `base_score` and adds the value of the leaf
 *      each of its trees reaches; summed in 64 bits, as the reference does;
 *   3. the softmax of these margins gives each class's probability;
 *   4. each class's probability is split over its answers by `classes`.
 *
 * Mask and choice (Choice.h) come after. The file is read with BARb's jsoncpp
 * and only its arrays are kept: a node takes 20 bytes. One loaded file is
 * shared by every AI of the process (Shared), since several AIs play in one
 * game and the file is large. */

#ifndef REASON8_TREES_H
#define REASON8_TREES_H

#include "Model.h"

#include "json/json.h"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace reason8 {

inline const char* const TREES_FORMAT = "reason8.builder-trees/1";

class TreeModel {
public:
	struct Feature {
		std::string name;
		std::string group;
		bool categorical = false;
		std::unordered_map<std::string, int> codes;  // category -> its index
	};

	/* The model of a parsed file; null with `error` set when it is not one. */
	static std::shared_ptr<const TreeModel> FromJson(const Json::Value& document, std::string& error)
	{
		auto model = std::shared_ptr<TreeModel>(new TreeModel());
		try {
			if (!model->ReadHeader(document, error)) {
				return nullptr;
			}
			for (const Json::Value& tree : document["trees"]) {
				if (!model->ReadTree(tree, error)) {
					return nullptr;
				}
			}
		} catch (const std::exception& exception) {  // jsoncpp throws on a value of the wrong type
			error = std::string("malformed model file: ") + exception.what();
			return nullptr;
		}
		return model;
	}

	/* The model of the file at `path`; null with `error` set when it cannot be read.
	 * jsoncpp holds a parsed document in many times the memory of its text (about
	 * 2 GB for the 73 MB of the first model), so the trees are parsed one by one:
	 * the file without its trees, then each tree on its own. */
	static std::shared_ptr<const TreeModel> Load(const std::string& path, std::string& error)
	{
		std::ifstream file(path, std::ios::binary);
		if (!file.is_open()) {
			error = "cannot open " + path;
			return nullptr;
		}
		const std::string text((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
		std::vector<std::pair<std::size_t, std::size_t>> trees;  // [begin, end) of each tree
		std::size_t treesBegin = 0, treesEnd = 0;
		if (!FindTrees(text, treesBegin, treesEnd, trees)) {
			error = path + ": no \"trees\" array in the file";
			return nullptr;
		}
		Json::CharReaderBuilder builder;
		builder["allowSpecialFloats"] = true;  // a threshold can be -Infinity, as Python writes it
		const std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
		auto model = std::shared_ptr<TreeModel>(new TreeModel());
		try {
			const std::string header = text.substr(0, treesBegin) + "[]" + text.substr(treesEnd);
			Json::Value document;
			std::string errors;
			if (!reader->parse(header.data(), header.data() + header.size(), &document, &errors)) {
				error = path + ": " + errors;
				return nullptr;
			}
			if (!model->ReadHeader(document, error)) {
				return nullptr;
			}
			for (const auto& [begin, end] : trees) {
				Json::Value tree;
				if (!reader->parse(text.data() + begin, text.data() + end, &tree, &errors)) {
					error = path + ": " + errors;
					return nullptr;
				}
				if (!model->ReadTree(tree, error)) {
					return nullptr;
				}
			}
		} catch (const std::exception& exception) {
			error = path + ": malformed model file: " + exception.what();
			return nullptr;
		}
		return model;
	}

	/* The model of the file at `path`, loaded once per process for every AI that
	 * asks while one of them holds it. `loaded` says whether this call read it. */
	static std::shared_ptr<const TreeModel> Shared(const std::string& path, std::string& error, bool& loaded)
	{
		static std::mutex mutex;
		static std::map<std::string, std::weak_ptr<const TreeModel>> models;
		const std::lock_guard<std::mutex> lock(mutex);
		std::shared_ptr<const TreeModel> model = models[path].lock();
		loaded = model == nullptr;
		if (loaded) {
			model = Load(path, error);
			models[path] = model;
		}
		return model;
	}

	const std::string& Name() const { return name; }
	const std::vector<std::string>& AnswerNames() const { return answers; }
	const std::vector<Feature>& Features() const { return features; }
	const std::string& Unknown() const { return unknown; }
	float Threshold() const { return threshold; }
	/* The quantiles of skill in training, by quantile ("0.9"); empty when the file has none. */
	const std::map<std::string, double>& SkillQuantiles() const { return skillQuantiles; }
	bool HasFeature(const std::string& featureName) const
	{
		for (const Feature& feature : features) {
			if (feature.name == featureName) {
				return true;
			}
		}
		return false;
	}
	std::size_t Trees() const { return treeClass.size(); }
	std::size_t Nodes() const { return nodes.size(); }
	std::size_t Classes() const { return baseScore.size(); }
	/* What the arrays take, in bytes. */
	std::size_t Bytes() const
	{
		std::size_t bytes = nodes.size() * sizeof(Node) + treeRoot.size() * sizeof(std::int32_t)
			+ treeClass.size() * sizeof(std::int32_t) + categorySets.size() * sizeof(std::uint64_t);
		for (const auto& entries : classAnswers) {
			bytes += entries.size() * sizeof(entries[0]);
		}
		return bytes;
	}

	/* Step 1: the row the trees read. */
	std::vector<float> Encode(const Inputs& inputs) const
	{
		std::vector<float> row(features.size(), std::numeric_limits<float>::quiet_NaN());
		for (std::size_t index = 0; index < features.size(); ++index) {
			const Feature& feature = features[index];
			if (feature.categorical) {
				const std::string* value = inputs.Name(feature.name);
				if (value != nullptr) {
					const auto code = feature.codes.find(*value);
					if (code != feature.codes.end()) {
						row[index] = static_cast<float>(code->second);
					}
				}
			} else {
				const double* value = inputs.Number(feature.name);
				if (value != nullptr) {
					row[index] = static_cast<float>(*value);
				}
			}
		}
		return row;
	}

	/* Steps 2 and 3: the probability of each class for an encoded row. */
	std::vector<double> ClassProbabilities(const std::vector<float>& row) const
	{
		std::vector<double> margins(baseScore.begin(), baseScore.end());
		for (std::size_t tree = 0; tree < treeRoot.size(); ++tree) {
			margins[treeClass[tree]] += Leaf(treeRoot[tree], row);
		}
		double largest = -std::numeric_limits<double>::infinity();
		for (const double margin : margins) {
			largest = std::max(largest, margin);
		}
		double total = 0.0;
		for (double& margin : margins) {
			margin = std::exp(margin - largest);
			total += margin;
		}
		for (double& margin : margins) {
			margin /= total;
		}
		return margins;
	}

	/* Steps 2 to 4: the probability of every answer, in the order of the file's
	 * `answers`. */
	Answers Predict(const std::vector<float>& row) const
	{
		const std::vector<double> classes = ClassProbabilities(row);
		std::vector<double> shares(answers.size(), 0.0);
		for (std::size_t index = 0; index < classes.size(); ++index) {
			for (const auto& [answer, weight] : classAnswers[index]) {
				shares[answer] += classes[index] * weight;
			}
		}
		Answers result;
		result.reserve(answers.size());
		for (std::size_t index = 0; index < answers.size(); ++index) {
			result.push_back({answers[index], static_cast<float>(shares[index])});
		}
		return result;
	}

	Answers Predict(const Inputs& inputs) const { return Predict(Encode(inputs)); }

private:
	/* A split node or a leaf. A split sends a missing input to `defaultLeft`'s
	 * side, a code of its category set (`categories`, an offset into
	 * categorySets, -1 for a numeric split) right, a number below `value` left. */
	struct Node {
		float value;          // threshold of a split, value of a leaf
		std::int32_t left;    // absolute node indices
		std::int32_t right;
		std::int32_t categories;
		std::int16_t feature;  // -1: a leaf
		std::uint8_t defaultLeft;
		std::uint8_t categoryWords;  // 64-bit words of the set
	};

	TreeModel() = default;

	double Leaf(std::int32_t index, const std::vector<float>& row) const
	{
		const Node* node = &nodes[index];
		while (node->feature >= 0) {
			const float value = row[node->feature];
			bool left;
			if (std::isnan(value)) {
				left = node->defaultLeft != 0;
			} else if (node->categories >= 0) {
				left = !InSet(*node, value);
			} else {
				left = value < node->value;
			}
			node = &nodes[left ? node->left : node->right];
		}
		return node->value;
	}

	bool InSet(const Node& node, float value) const
	{
		if (value < 0.f || value != std::floor(value)) {
			return false;
		}
		const auto code = static_cast<std::uint64_t>(value);
		if (code >= 64u * node.categoryWords) {
			return false;
		}
		return (categorySets[node.categories + code / 64] >> (code % 64)) & 1u;
	}

	/* Finds the top-level "trees" array of a model file's text: its span and the
	 * span of each element. Brackets inside strings do not count. */
	static bool FindTrees(const std::string& text, std::size_t& arrayBegin, std::size_t& arrayEnd,
			std::vector<std::pair<std::size_t, std::size_t>>& trees)
	{
		int depth = 0;
		std::size_t index = 0;
		const std::size_t size = text.size();
		auto skipString = [&]() {  // from the opening quote to past the closing one
			for (++index; index < size && text[index] != '"'; ++index) {
				if (text[index] == '\\') {
					++index;
				}
			}
			++index;
		};
		while (index < size) {
			const char character = text[index];
			if (character == '"') {
				const std::size_t keyBegin = index;
				skipString();
				if (depth != 1 || text.compare(keyBegin, 7, "\"trees\"") != 0 || index != keyBegin + 7) {
					continue;
				}
				while (index < size && (std::isspace(static_cast<unsigned char>(text[index])) || text[index] == ':')) {
					++index;
				}
				if (index >= size || text[index] != '[') {
					return false;
				}
				arrayBegin = index++;
				int inner = 0;
				std::size_t treeBegin = 0;
				while (index < size) {
					const char item = text[index];
					if (item == '"') {
						skipString();
						continue;
					}
					if (item == '{' || item == '[') {
						if (inner++ == 0) {
							treeBegin = index;
						}
					} else if (item == '}' || item == ']') {
						if (inner == 0) {  // the end of the trees
							arrayEnd = index + 1;
							return true;
						}
						if (--inner == 0) {
							trees.emplace_back(treeBegin, index + 1);
						}
					}
					++index;
				}
				return false;
			}
			if (character == '{' || character == '[') {
				++depth;
			} else if (character == '}' || character == ']') {
				--depth;
			}
			++index;
		}
		return false;
	}

	bool ReadHeader(const Json::Value& document, std::string& error)
	{
		if (!document.isObject() || document["format"].asString() != TREES_FORMAT) {
			error = std::string("not a ") + TREES_FORMAT + " file";
			return false;
		}
		name = document["name"].asString();
		for (const Json::Value& answer : document["answers"]) {
			answers.push_back(answer.asString());
		}
		unknown = document["choice"]["unknown"].asString();
		const Json::Value& quantiles = document["training"]["skill_quantiles"];
		if (quantiles.isObject()) {
			for (const std::string& quantile : quantiles.getMemberNames()) {
				skillQuantiles[quantile] = quantiles[quantile].asDouble();
			}
		}
		threshold = document["choice"]["threshold"].asFloat();
		for (const Json::Value& entry : document["features"]) {
			Feature feature;
			feature.name = entry["name"].asString();
			feature.group = entry["group"].asString();
			feature.categorical = entry["type"].asString() == "categorical";
			int code = 0;
			for (const Json::Value& category : entry["categories"]) {
				feature.codes.emplace(category.asString(), code++);
			}
			features.push_back(std::move(feature));
		}
		for (const Json::Value& entry : document["classes"]) {
			std::vector<std::pair<std::int32_t, double>> shares;
			const Json::Value& weights = entry["weights"];
			Json::ArrayIndex position = 0;
			for (const Json::Value& answer : entry["answers"]) {
				const int index = answer.asInt();
				if (index < 0 || index >= static_cast<int>(answers.size()) || position >= weights.size()) {
					error = "a class names an answer the file does not have";
					return false;
				}
				shares.emplace_back(index, weights[position++].asDouble());
			}
			classAnswers.push_back(std::move(shares));
		}
		for (const Json::Value& score : document["base_score"]) {
			baseScore.push_back(score.asFloat());
		}
		if (baseScore.size() != classAnswers.size() || baseScore.empty()) {
			error = "base_score and classes differ in length";
			return false;
		}
		return true;
	}

	bool ReadTree(const Json::Value& tree, std::string& error)
	{
		const int treeClassIndex = tree["class"].asInt();
		if (treeClassIndex < 0 || treeClassIndex >= static_cast<int>(baseScore.size())) {
			error = "a tree of a class the file does not have";
			return false;
		}
		std::vector<int> feature, left, right, defaultLeft;
		std::vector<float> threshold, value;
		for (const Json::Value& item : tree["feature"]) feature.push_back(item.asInt());
		for (const Json::Value& item : tree["left"]) left.push_back(item.asInt());
		for (const Json::Value& item : tree["right"]) right.push_back(item.asInt());
		for (const Json::Value& item : tree["default_left"]) defaultLeft.push_back(item.asInt());
		for (const Json::Value& item : tree["threshold"]) threshold.push_back(item.asFloat());
		for (const Json::Value& item : tree["value"]) value.push_back(item.asFloat());
		const std::size_t count = feature.size();
		if (count == 0 || left.size() != count || right.size() != count || defaultLeft.size() != count
				|| threshold.size() != count || value.size() != count) {
			error = "a tree's arrays differ in length";
			return false;
		}
		const auto base = static_cast<std::int32_t>(nodes.size());
		for (std::size_t index = 0; index < count; ++index) {
			Node node{};
			node.feature = static_cast<std::int16_t>(feature[index] < 0 ? -1 : feature[index]);
			node.categories = -1;
			if (node.feature >= 0) {
				if (feature[index] >= static_cast<int>(features.size()) || left[index] <= 0 || right[index] <= 0
						|| left[index] >= static_cast<int>(count) || right[index] >= static_cast<int>(count)) {
					error = "a tree's split points outside the tree or the inputs";
					return false;
				}
				node.value = threshold[index];
				node.left = base + left[index];
				node.right = base + right[index];
				node.defaultLeft = defaultLeft[index] != 0;
			} else {
				node.value = value[index];
			}
			nodes.push_back(node);
		}
		for (const Json::Value& entry : tree["categories"]) {
			const int index = entry[0].asInt();
			if (index < 0 || index >= static_cast<int>(count) || feature[index] < 0) {
				error = "a category set of a node that is no split";
				return false;
			}
			int largest = -1;
			for (const Json::Value& code : entry[1]) {
				largest = std::max(largest, code.asInt());
			}
			const int words = largest / 64 + 1;
			if (words > 255) {
				error = "a category set too large";
				return false;
			}
			Node& node = nodes[base + index];
			node.categories = static_cast<std::int32_t>(categorySets.size());
			node.categoryWords = static_cast<std::uint8_t>(words);
			categorySets.resize(categorySets.size() + words, 0);
			for (const Json::Value& code : entry[1]) {
				const int bit = code.asInt();
				if (bit >= 0) {
					categorySets[node.categories + bit / 64] |= std::uint64_t{1} << (bit % 64);
				}
			}
		}
		treeRoot.push_back(base);
		treeClass.push_back(treeClassIndex);
		return true;
	}

	std::string name;
	std::vector<std::string> answers;
	std::string unknown;
	float threshold = CHOICE_THRESHOLD;
	std::map<std::string, double> skillQuantiles;
	std::vector<Feature> features;
	std::vector<std::vector<std::pair<std::int32_t, double>>> classAnswers;  // class -> (answer, share)
	std::vector<float> baseScore;
	std::vector<Node> nodes;
	std::vector<std::int32_t> treeRoot;
	std::vector<std::int32_t> treeClass;
	std::vector<std::uint64_t> categorySets;
};

}  // namespace reason8

#endif  // REASON8_TREES_H
