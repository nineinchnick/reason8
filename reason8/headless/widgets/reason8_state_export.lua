--------------------------------------------------------------------------------
-- reason8_state_export.lua -- game state snapshots, written while a game or a
-- replay runs in spring-headless.
--
-- A replay records commands, not the world. Played back by the engine, with
-- this widget loaded as a full-view spectator, it writes what the world looked
-- like: every second one line with every team's resources and the wind, every
-- N seconds one line with the type, owner, position, health and build progress
-- of every unit that can move or is still being built, one line per unit
-- created / finished / destroyed / given, one when a factory or builder goes
-- idle, and the damage enemies do to each other. Finished buildings are not in
-- the snapshots: they do not move, and the unit lines say where and when each
-- one was made, finished, given and destroyed. The widget is unsynced and
-- gives no orders, so the replay stays valid.
--
-- Wrecks and other reclaimable features (format 6): one line per feature with
-- metal or energy when it appears (those of the map at the start), and when
-- it goes, with what was left and whether it was reclaimed away; the unit line
-- of a resurrected unit names its feature. What every builder works on (build,
-- repair, reclaim, resurrect, capture, restore) has no call-in a widget gets,
-- so it is sampled: every Reason8WorkFrames the widget asks each builder and
-- writes a line when the task or its target changed. The metal and energy a
-- feature gives up between two samples go to the teams reclaiming it, and
-- what it had left when reclaimed away to the builders working on it in that
-- frame, which the widget asks right then.
--
-- Resource and snapshot lines are written in GameFramePost, after everything
-- that happened in the frame, so a line of frame F shows the world after the
-- unit lines of frames up to F. An engine without GameFramePost gets them in
-- GameFrame instead, at the start of the frame; the end line then says
-- "sampled":"frame_start".
--
-- The approach (spectator widget + headless playback at max speed) follows
-- Apex's barai_replay_export.lua (github.com/apexearth/bar-ai, GPL v2+); the
-- code here is our own.
--
-- Output: JSON lines in LuaUI/Config/reason8_state.jsonl under the write dir
-- (LuaUI/Config is one of the two folders BAR lets a user widget write to).
-- Settings come from springsettings.cfg, written by reason8/headless/run.py:
--   Reason8SnapshotFrames  frames between snapshots (default 150 = 5 s, 0 = off)
--   Reason8ResourceFrames  frames between resource lines (default 30 = 1 s)
--   Reason8Speed           game speed to ask for (default 0 = leave alone)
--   Reason8MaxFrame        quit at this frame (default 0 = only at game over)
--   Reason8Events          1 = also write per-unit event lines (default 1)
--   Reason8WorkFrames      frames between samples of builders' work (default 5,
--                          0 = off); only with events
--
-- No player names are written: teams and players are numbers only.
--------------------------------------------------------------------------------

function widget:GetInfo()
	return {
		name = "Reason8 state export",
		desc = "Writes game state snapshots to LuaUI/Config/reason8_state.jsonl",
		author = "Reason8",
		date = "2026",
		license = "GNU GPL, v2",
		layer = 0,
		enabled = true,
	}
end

local OUT_PATH = "LuaUI/Config/reason8_state.jsonl"
-- 2: hit and damage lines, wind; 3: exact attacker; 4: idle; 5: resource lines every
-- second, snapshots at the end of the frame and without finished buildings; 6: features,
-- reclaim, builders' work, resurrected units' features, attacker of a destroyed unit
local FORMAT_VERSION = 6

local spGetGameFrame = Spring.GetGameFrame
local spGetAllUnits = Spring.GetAllUnits
local spGetUnitDefID = Spring.GetUnitDefID
local spGetUnitTeam = Spring.GetUnitTeam
local spGetUnitPosition = Spring.GetUnitPosition
local spGetUnitHealth = Spring.GetUnitHealth
local spGetUnitIsDead = Spring.GetUnitIsDead
local spGetTeamResources = Spring.GetTeamResources
local spGetUnitLastAttacker = Spring.GetUnitLastAttacker
local spGetWind = Spring.GetWind
local spGetUnitWorkerTask = Spring.GetUnitWorkerTask
local spGetFeatureDefID = Spring.GetFeatureDefID
local spGetFeaturePosition = Spring.GetFeaturePosition
local spGetFeatureResources = Spring.GetFeatureResources
local spGetFeatureResurrect = Spring.GetFeatureResurrect
local spGetFeatureRadius = Spring.GetFeatureRadius
local spGetUnitsInCylinder = Spring.GetUnitsInCylinder
local floor = math.floor
local format = string.format
local concat = table.concat

local snapshotFrames = Spring.GetConfigInt("Reason8SnapshotFrames", 150)
local resourceFrames = Spring.GetConfigInt("Reason8ResourceFrames", 30)
local wantedSpeed = Spring.GetConfigInt("Reason8Speed", 0)
local maxFrame = Spring.GetConfigInt("Reason8MaxFrame", 0)
local writeEvents = Spring.GetConfigInt("Reason8Events", 1) ~= 0
local workFrames = writeEvents and Spring.GetConfigInt("Reason8WorkFrames", 5) or 0

local DAMAGE_FRAMES = 30 -- damage between teams is summed over this many frames

local outputFile
local teams = {}
local allyTeamOfTeam = {}
local gaiaTeam = Spring.GetGaiaTeamID()
local finished = false
local isStatic = {} -- [unitDefID] = true for units that cannot move
local lastResourceFrame, lastSnapshotFrame = -1, -1
local framePostSeen = false -- the engine calls GameFramePost
local sampleAtFrameStart = false -- it doesn't: sample in GameFrame instead
-- damage by enemies: who has hit which unit already, and the sums not yet written
local hitBefore = {} -- [unitID] = { [attackerTeam] = true }
local damageSums = {} -- [victimTeam * 256 + attackerTeam] = { hits, damage }

-- features and builders' work (format 6)
local MAX_UNITS = Game.maxUnits -- a builder's target above this is a feature: id + MAX_UNITS
local CMD_RECLAIM, CMD_RESURRECT = CMD.RECLAIM, CMD.RESURRECT
local TASK_NAMES = { [CMD.REPAIR] = "repair", [CMD.RECLAIM] = "reclaim", [CMD.RESURRECT] = "resurrect" }
if CMD.CAPTURE then
	TASK_NAMES[CMD.CAPTURE] = "capture"
end
if CMD.RESTORE then
	TASK_NAMES[CMD.RESTORE] = "restore"
end
-- [unitDefID] = how fast it reclaims, for units that can build, assist or reclaim, not factories
local isBuilder = {}
local maxBuildDistance = 0
local features = {} -- [featureID] = { metal, energy, reclaimLeft } as last seen, for the features written
local featureDefSeen = {} -- [featureDefID] = true once its "fdef" line is written
local builders, builderList, builderListDirty = {}, {}, false
local lastTask = {} -- [builderID] = "task target" as last written
local reclaimersBefore = {} -- [featureID] = { [team] = reclaim speed } at the last sample
local reclaimSums = {} -- [featureID] = { [team] = { metal, energy, firstFrame } } not yet written

local function write(line)
	if outputFile then
		outputFile:write(line, "\n")
	else
		Spring.Echo("[R8] " .. line) -- no file access: fall back to the engine log
	end
end

local function jsonString(value)
	return '"' .. tostring(value):gsub('[%c"\\]', function(character)
		return format("\\u%04x", character:byte())
	end) .. '"'
end

local function writeHeader()
	-- pairs() has no fixed order; the file must not depend on it
	local unitDefIDs = {}
	for unitDefID in pairs(UnitDefs) do
		unitDefIDs[#unitDefIDs + 1] = unitDefID
	end
	table.sort(unitDefIDs)
	local unitDefNames, staticIDs, builderIDs = {}, {}, {}
	for i = 1, #unitDefIDs do
		local unitDefID = unitDefIDs[i]
		local unitDef = UnitDefs[unitDefID]
		unitDefNames[#unitDefNames + 1] = format("%s:%s", jsonString(unitDefID), jsonString(unitDef.name))
		local immobile = unitDef.isImmobile
		if immobile == nil then
			immobile = (unitDef.speed or 0) <= 0 and not unitDef.canFly
		end
		if immobile then
			isStatic[unitDefID] = true
			staticIDs[#staticIDs + 1] = unitDefID
		end
		if (unitDef.isBuilder or unitDef.canReclaim or unitDef.canResurrect) and not unitDef.isFactory then
			isBuilder[unitDefID] = math.max(unitDef.reclaimSpeed or unitDef.buildSpeed or 0, 1)
			builderIDs[#builderIDs + 1] = unitDefID
			maxBuildDistance = math.max(maxBuildDistance, unitDef.buildDistance or 0)
		end
	end
	local teamParts = {}
	for _, team in ipairs(Spring.GetTeamList()) do
		local _, _, _, isAI, side, allyTeam = Spring.GetTeamInfo(team, false)
		teams[#teams + 1] = team
		allyTeamOfTeam[team] = allyTeam
		teamParts[#teamParts + 1] = format(
			'{"team":%d,"ally":%d,"ai":%s,"side":%s,"gaia":%s}',
			team,
			allyTeam or -1,
			isAI and "true" or "false",
			jsonString(side or ""),
			team == gaiaTeam and "true" or "false"
		)
	end
	write(
		format(
			'{"t":"header","v":%d,"game":%s,"map":%s,"engine":%s,"mapx":%d,"mapz":%d,'
				.. '"replay":%s,"snapshot_frames":%d,"resource_frames":%d,"work_frames":%d,'
				.. '"wind_min":%.1f,"wind_max":%.1f,"tidal":%.1f,'
				.. '"teams":[%s],"unitdefs":{%s},"static":[%s],"builders":[%s]}',
			FORMAT_VERSION,
			jsonString(Game.gameName .. " " .. Game.gameVersion),
			jsonString(Game.mapName),
			jsonString(Engine.version),
			Game.mapSizeX,
			Game.mapSizeZ,
			Spring.IsReplay() and "true" or "false",
			snapshotFrames,
			resourceFrames,
			workFrames,
			Game.windMin or -1,
			Game.windMax or -1,
			Game.tidal or -1,
			concat(teamParts, ","),
			concat(unitDefNames, ","),
			concat(staticIDs, ","),
			concat(builderIDs, ",")
		)
	)
end

-- One line per second with every team's resources and the wind strength at
-- that moment (it changes all the time, and with it what a wind turbine
-- makes). Arrays, not objects, to keep it small:
--   teams: [team, metal, metalStorage, metalIncome, metalExpense,
--           energy, energyStorage, energyIncome, energyExpense]
local function writeResources(frame)
	lastResourceFrame = frame
	local teamParts = {}
	for i = 1, #teams do
		local team = teams[i]
		local metal, metalStorage, _, metalIncome, metalExpense = spGetTeamResources(team, "metal")
		local energy, energyStorage, _, energyIncome, energyExpense = spGetTeamResources(team, "energy")
		if metal then
			teamParts[#teamParts + 1] = format(
				"[%d,%d,%d,%.1f,%.1f,%d,%d,%.0f,%.0f]",
				team,
				metal,
				metalStorage,
				metalIncome,
				metalExpense,
				energy,
				energyStorage,
				energyIncome,
				energyExpense
			)
		end
	end
	local _, _, _, windStrength = spGetWind()
	write(format('{"t":"r","f":%d,"wind":%.2f,"teams":[%s]}', frame, windStrength or -1, concat(teamParts, ",")))
end

-- One line per snapshot with every unit that can move or is still being built,
-- by unit id. A unit that was destroyed and is still dying (its death
-- animation) is left out: it had its "destroyed" line already.
--   units: [unitID, unitDefID, team, x, z, health%, build%]
local function writeSnapshot(frame)
	lastSnapshotFrame = frame
	local unitParts = {}
	local units = spGetAllUnits()
	table.sort(units)
	for i = 1, #units do
		local unitID = units[i]
		local unitDefID = spGetUnitDefID(unitID)
		if unitDefID and not spGetUnitIsDead(unitID) then
			local health, maxHealth, _, _, buildProgress = spGetUnitHealth(unitID)
			buildProgress = buildProgress or 1
			if not (isStatic[unitDefID] and buildProgress >= 1) then
				local x, _, z = spGetUnitPosition(unitID)
				if x then
					local healthPercent = (health and maxHealth and maxHealth > 0) and floor(100 * health / maxHealth) or 0
					unitParts[#unitParts + 1] = format(
						"[%d,%d,%d,%d,%d,%d,%d]",
						unitID,
						unitDefID,
						spGetUnitTeam(unitID) or -1,
						x,
						z,
						healthPercent < 0 and 0 or healthPercent,
						floor(100 * buildProgress)
					)
				end
			end
		end
	end
	write(format('{"t":"s","f":%d,"units":[%s]}', frame, concat(unitParts, ",")))
end

local function writeEvent(kind, unitID, unitDefID, unitTeam, extra)
	if not writeEvents or finished then
		return
	end
	local x, _, z = spGetUnitPosition(unitID)
	write(
		format(
			'{"t":"%s","f":%d,"u":%d,"d":%d,"team":%d,"x":%d,"z":%d%s}',
			kind,
			spGetGameFrame(),
			unitID,
			unitDefID or -1,
			unitTeam or -1,
			x or -1,
			z or -1,
			extra or ""
		)
	)
end

-- Features: wrecks, heaps, rocks and trees, the ones with metal or energy to reclaim.
--   "fdef": a feature type, the first time one is written: its name, metal, energy
--          and reclaim time
--   "fcreated": a feature that appeared, with its type, position, metal and energy,
--          and for a wreck the unit type it can be resurrected as ("rez"); the map's
--          own at the frame the widget starts
--   "fdestroyed": a feature gone, with the metal and energy it had left and how
--          much of its reclaim was left (0: reclaimed away)
--   "reclaim": metal and energy a team took from a feature, from frame "from"
--          to frame "f": written when the team stops reclaiming it, when it is
--          gone, and at the end
local function writeFeatureDef(featureDefID)
	featureDefSeen[featureDefID] = true
	local featureDef = FeatureDefs[featureDefID]
	write(
		format(
			'{"t":"fdef","d":%d,"name":%s,"metal":%.0f,"energy":%.0f,"reclaim_time":%.0f}',
			featureDefID,
			jsonString(featureDef and featureDef.name or ""),
			featureDef and featureDef.metal or 0,
			featureDef and featureDef.energy or 0,
			featureDef and featureDef.reclaimTime or 0
		)
	)
end

local function addFeature(featureID)
	if features[featureID] or finished then
		return
	end
	local featureDefID = spGetFeatureDefID(featureID)
	local featureDef = featureDefID and FeatureDefs[featureDefID]
	if not featureDef or featureDef.reclaimable == false then
		return
	end
	local metal, _, energy, _, reclaimLeft = spGetFeatureResources(featureID)
	if not metal or (metal <= 0 and energy <= 0) then
		return
	end
	features[featureID] = { metal, energy, reclaimLeft }
	if not featureDefSeen[featureDefID] then
		writeFeatureDef(featureDefID)
	end
	local resurrectAs = spGetFeatureResurrect(featureID)
	local resurrectDef = resurrectAs and resurrectAs ~= "" and UnitDefNames[resurrectAs]
	local x, _, z = spGetFeaturePosition(featureID)
	write(
		format(
			'{"t":"fcreated","f":%d,"id":%d,"d":%d,"x":%d,"z":%d,"metal":%.1f,"energy":%.1f%s}',
			spGetGameFrame(),
			featureID,
			featureDefID,
			x or -1,
			z or -1,
			metal,
			energy,
			resurrectDef and format(',"rez":%d', resurrectDef.id) or ""
		)
	)
end

local function writeReclaim(featureID, team, sums, frame)
	if sums[1] > 0.05 or sums[2] > 0.05 then
		write(
			format(
				'{"t":"reclaim","f":%d,"id":%d,"team":%d,"from":%d,"metal":%.1f,"energy":%.1f}',
				frame,
				featureID,
				team,
				sums[3],
				sums[1],
				sums[2]
			)
		)
	end
end

-- What a feature gave up to reclaim since it was last seen goes to `teams` ({ [team] =
-- reclaim speed of its builders on it }), split by that speed. Only what went with its reclaim
-- progress, while a builder was seen on it, counts: the game takes the metal and energy
-- of a tree that an explosion fells, and its reclaim progress with it.
local function creditReclaim(featureID, metal, energy, reclaimLeft, teams, frame)
	local seen = features[featureID]
	if not seen or not metal then
		return
	end
	local metalTaken, energyTaken = seen[1] - metal, seen[2] - energy
	local reclaimed = reclaimLeft < seen[3]
	seen[1], seen[2], seen[3] = metal, energy, reclaimLeft
	if not reclaimed or (metalTaken <= 0 and energyTaken <= 0) then
		return -- repaired before it is resurrected, taken by the game, or nothing taken
	end
	metalTaken, energyTaken = math.max(metalTaken, 0), math.max(energyTaken, 0)
	local total = 0
	for _, speed in pairs(teams or {}) do
		total = total + speed
	end
	if total == 0 then
		return
	end
	local sums = reclaimSums[featureID]
	if not sums then
		sums = {}
		reclaimSums[featureID] = sums
	end
	for team, speed in pairs(teams) do
		local teamSums = sums[team]
		if not teamSums then
			teamSums = { 0, 0, frame }
			sums[team] = teamSums
		end
		teamSums[1] = teamSums[1] + metalTaken * speed / total
		teamSums[2] = teamSums[2] + energyTaken * speed / total
	end
end

-- Write a feature's reclaim sums: of every team, or of the teams no longer on it.
local function flushReclaim(featureID, frame, teamsStillOn)
	local sums = reclaimSums[featureID]
	if not sums then
		return
	end
	local teamIDs = {}
	for team in pairs(sums) do
		if not (teamsStillOn and teamsStillOn[team]) then
			teamIDs[#teamIDs + 1] = team
		end
	end
	table.sort(teamIDs)
	for i = 1, #teamIDs do
		writeReclaim(featureID, teamIDs[i], sums[teamIDs[i]], frame)
		sums[teamIDs[i]] = nil
	end
	if next(sums) == nil then
		reclaimSums[featureID] = nil
	end
end

-- The builders reclaiming a feature right now, by team: asked when it is reclaimed away,
-- while the builders that took its last step still point at it.
local function reclaimersNow(featureID)
	local x, _, z = spGetFeaturePosition(featureID)
	if not x then
		return nil
	end
	local radius = maxBuildDistance + (spGetFeatureRadius(featureID) or 0) + 100
	local teams
	local units = spGetUnitsInCylinder(x, z, radius)
	for i = 1, #units do
		local unitID = units[i]
		if builders[unitID] then
			local task, target = spGetUnitWorkerTask(unitID)
			if task == CMD_RECLAIM and target == featureID + MAX_UNITS then
				local team = spGetUnitTeam(unitID)
				teams = teams or {}
				teams[team] = (teams[team] or 0) + builders[unitID]
			end
		end
	end
	return teams
end

function widget:FeatureCreated(featureID)
	if writeEvents then
		addFeature(featureID)
	end
end

function widget:FeatureDestroyed(featureID)
	if not features[featureID] or finished then
		return
	end
	local frame = spGetGameFrame()
	local metal, _, energy, _, reclaimLeft = spGetFeatureResources(featureID)
	if metal then
		local teams = reclaimersBefore[featureID]
		if reclaimLeft and reclaimLeft <= 0 then
			teams = reclaimersNow(featureID) or teams
		end
		creditReclaim(featureID, metal, energy, reclaimLeft, teams, frame)
	end
	flushReclaim(featureID, frame)
	write(
		format(
			'{"t":"fdestroyed","f":%d,"id":%d,"metal":%.1f,"energy":%.1f,"reclaim_left":%.3f}',
			frame,
			featureID,
			metal or -1,
			energy or -1,
			reclaimLeft or -1
		)
	)
	features[featureID] = nil
	reclaimersBefore[featureID] = nil
end

-- What every builder works on, written when it changed since the last sample:
--   "work": builder, its team, the task (build, repair, reclaim, resurrect, capture,
--          restore, or none) and its target, a unit ("unit") or a feature ("feature").
--          Building a unit someone else started is assisting it
-- and the metal and energy that the features being reclaimed gave up since the sample before.
local function addBuilder(unitID, unitDefID)
	if workFrames > 0 and isBuilder[unitDefID] and not builders[unitID] then
		builders[unitID] = isBuilder[unitDefID]
		builderListDirty = true
	end
end

local function removeBuilder(unitID)
	if builders[unitID] then
		builders[unitID] = nil
		lastTask[unitID] = nil
		builderListDirty = true
	end
end

local function sampleWork(frame)
	if builderListDirty then
		builderList = {}
		for unitID in pairs(builders) do
			builderList[#builderList + 1] = unitID
		end
		table.sort(builderList) -- the file must not depend on the order of pairs()
		builderListDirty = false
	end
	local reclaimers = {} -- [featureID] = { [team] = reclaim speed }
	for i = 1, #builderList do
		local unitID = builderList[i]
		local task, target = spGetUnitWorkerTask(unitID)
		local name, targetField = "none", ""
		if task then
			if task < 0 then
				name = "build"
			else
				name = TASK_NAMES[task] or tostring(task)
			end
			if target then
				if target >= MAX_UNITS then
					local featureID = target - MAX_UNITS
					targetField = format(',"feature":%d', featureID)
					if task == CMD_RECLAIM then
						local team = spGetUnitTeam(unitID) or -1
						local teams = reclaimers[featureID]
						if not teams then
							teams = {}
							reclaimers[featureID] = teams
						end
						teams[team] = (teams[team] or 0) + builders[unitID]
					end
				else
					targetField = format(',"unit":%d', target)
				end
			end
		end
		local key = name .. targetField
		if lastTask[unitID] ~= key then
			if not (lastTask[unitID] == nil and name == "none") then
				write(
					format(
						'{"t":"work","f":%d,"u":%d,"team":%d,"task":"%s"%s}',
						frame,
						unitID,
						spGetUnitTeam(unitID) or -1,
						name,
						targetField
					)
				)
			end
			lastTask[unitID] = key
		end
	end
	-- features reclaimed now or at the last sample: what they gave up since, and the
	-- sums of the teams that left them
	local featureIDs = {}
	for featureID in pairs(reclaimers) do
		featureIDs[#featureIDs + 1] = featureID
	end
	for featureID in pairs(reclaimersBefore) do
		if not reclaimers[featureID] then
			featureIDs[#featureIDs + 1] = featureID
		end
	end
	table.sort(featureIDs)
	for i = 1, #featureIDs do
		local featureID = featureIDs[i]
		if features[featureID] then
			local metal, _, energy, _, reclaimLeft = spGetFeatureResources(featureID)
			creditReclaim(
				featureID,
				metal,
				energy,
				reclaimLeft,
				reclaimers[featureID] or reclaimersBefore[featureID],
				frame
			)
			flushReclaim(featureID, frame, reclaimers[featureID])
		end
	end
	reclaimersBefore = reclaimers
end

-- Damage one side does to the other, in two kinds of lines:
--   "hit": the first time a team's unit damages a given enemy unit, with both
--          units' types, so that who met whom, and when, can be told apart
--   "damage": hits and damage per victim team and attacking team, summed over
--          DAMAGE_FRAMES frames, so that a poke can be told from a fight
-- Damage from or to the neutral team is not written.
local function recordDamage(unitID, unitDefID, unitTeam, damage, paralyzer, attackerID, attackerDefID, attackerTeam)
	if finished or not attackerTeam or not unitTeam then
		return
	end
	local victimAllyTeam, attackerAllyTeam = allyTeamOfTeam[unitTeam], allyTeamOfTeam[attackerTeam]
	if victimAllyTeam == attackerAllyTeam or unitTeam == gaiaTeam or attackerTeam == gaiaTeam then
		return
	end
	local key = unitTeam * 256 + attackerTeam
	local sums = damageSums[key]
	if not sums then
		sums = { 0, 0 }
		damageSums[key] = sums
	end
	sums[1] = sums[1] + 1
	sums[2] = sums[2] + (damage or 0)
	local attackers = hitBefore[unitID]
	if not attackers then
		attackers = {}
		hitBefore[unitID] = attackers
	end
	if not attackers[attackerTeam] then
		attackers[attackerTeam] = true
		writeEvent(
			"hit",
			unitID,
			unitDefID,
			unitTeam,
			format(
				',"by":%d,"by_d":%d,"by_team":%d,"damage":%.0f,"paralyzer":%s',
				attackerID or -1,
				attackerDefID or -1,
				attackerTeam,
				damage or 0,
				paralyzer and "true" or "false"
			)
		)
	end
end

-- Who did the damage. BAR's widget handler gives a widget only the first five
-- arguments of UnitDamaged, so the attacker is asked from the engine instead:
-- Spring.GetUnitLastAttacker returns the unit that last damaged the unit. It
-- works the same in every game version, needs no access to the handler, and is
-- left out when there is no attacker (debris, fire, terrain). It doesn't say
-- when that attack happened, so damage without an attacker of its own can be
-- put down to the unit's previous attacker; a unit's first hit is always right.
local attackerSource = "none"

function widget:UnitDamaged(unitID, unitDefID, unitTeam, damage, paralyzer)
	if not writeEvents or not unitTeam or unitTeam == gaiaTeam then
		return
	end
	local attackerID = spGetUnitLastAttacker(unitID)
	if not attackerID then
		return
	end
	local attackerTeam = spGetUnitTeam(attackerID)
	if not attackerTeam then
		return
	end
	attackerSource = "last_attacker"
	recordDamage(unitID, unitDefID, unitTeam, damage, paralyzer, attackerID, spGetUnitDefID(attackerID), attackerTeam)
end

local function writeDamageSums(frame)
	local keys = {}
	for key in pairs(damageSums) do
		keys[#keys + 1] = key
	end
	table.sort(keys) -- pairs() has no fixed order; the file must not depend on it
	for i = 1, #keys do
		local key = keys[i]
		local sums = damageSums[key]
		write(
			format(
				'{"t":"damage","f":%d,"team":%d,"by_team":%d,"hits":%d,"damage":%.0f}',
				frame,
				floor(key / 256),
				key % 256,
				sums[1],
				sums[2]
			)
		)
		damageSums[key] = nil
	end
end

local function finish(reason, winners)
	if finished then
		return
	end
	local frame = spGetGameFrame()
	if writeEvents then
		-- what the features gave up since they were last seen, and every sum not written yet
		local featureIDs = {}
		for featureID in pairs(features) do
			featureIDs[#featureIDs + 1] = featureID
		end
		table.sort(featureIDs)
		for i = 1, #featureIDs do
			local featureID = featureIDs[i]
			local metal, _, energy, _, reclaimLeft = spGetFeatureResources(featureID)
			creditReclaim(featureID, metal, energy, reclaimLeft, reclaimersBefore[featureID], frame)
			flushReclaim(featureID, frame)
		end
		featureIDs = {}
		for featureID in pairs(reclaimSums) do
			featureIDs[#featureIDs + 1] = featureID
		end
		table.sort(featureIDs)
		for i = 1, #featureIDs do
			flushReclaim(featureIDs[i], frame)
		end
	end
	finished = true
	writeDamageSums(frame)
	if resourceFrames > 0 and lastResourceFrame ~= frame then
		writeResources(frame)
	end
	if snapshotFrames > 0 and lastSnapshotFrame ~= frame then
		writeSnapshot(frame)
	end
	-- the metal and energy each team reclaimed, as the game counts it: only game versions
	-- from late 2026 do, in team rules params
	local reclaimedParts = {}
	for i = 1, #teams do
		-- a param never set is no value at all, not nil: read into a local first
		local metal = Spring.GetTeamRulesParam(teams[i], "teamStatsReclaimedMetal")
		local energy = Spring.GetTeamRulesParam(teams[i], "teamStatsReclaimedEnergy")
		metal, energy = tonumber(metal), tonumber(energy)
		if metal or energy then
			reclaimedParts[#reclaimedParts + 1] = format("[%d,%.1f,%.1f]", teams[i], metal or 0, energy or 0)
		end
	end
	write(
		format(
			'{"t":"end","f":%d,"reason":%s,"winners":[%s],"attackers":%s,"sampled":%s%s}',
			frame,
			jsonString(reason),
			concat(winners or {}, ","),
			jsonString(attackerSource),
			jsonString(sampleAtFrameStart and "frame_start" or "frame_end"),
			#reclaimedParts > 0 and format(',"game_reclaimed":[%s]', concat(reclaimedParts, ",")) or ""
		)
	)
	if outputFile then
		outputFile:close()
		outputFile = nil
	end
end

function widget:Initialize()
	Spring.CreateDir("LuaUI/Config")
	outputFile = io.open(OUT_PATH, "w")
	writeHeader()
	Spring.SendCommands("specfullview 1")
	if writeEvents then
		-- the features already there: the map's own, before the game starts
		local featureIDs = Spring.GetAllFeatures()
		table.sort(featureIDs)
		for i = 1, #featureIDs do
			addFeature(featureIDs[i])
		end
		for _, unitID in ipairs(spGetAllUnits()) do
			local _, _, _, _, buildProgress = spGetUnitHealth(unitID)
			if (buildProgress or 0) >= 1 then
				addBuilder(unitID, spGetUnitDefID(unitID))
			end
		end
	end
	if wantedSpeed > 0 then
		-- a replay plays at 1x unless told otherwise; min = max pins the speed
		Spring.SendCommands("setmaxspeed " .. wantedSpeed, "setminspeed " .. wantedSpeed)
	end
	Spring.Echo(format("[R8] state export on: every %d frames, speed %d, max frame %d", snapshotFrames, wantedSpeed, maxFrame))
end

-- A unit made by a builder names it ("by"); one resurrected names its feature ("rez"):
-- while the unit is made, its resurrector still works on the feature.
function widget:UnitCreated(unitID, unitDefID, unitTeam, builderID)
	local extra
	if builderID then
		extra = format(',"by":%d', builderID)
		local task, target = spGetUnitWorkerTask(builderID)
		if task == CMD_RESURRECT and target and target >= MAX_UNITS then
			extra = extra .. format(',"rez":%d', target - MAX_UNITS)
		end
	end
	writeEvent("created", unitID, unitDefID, unitTeam, extra)
end

function widget:UnitFinished(unitID, unitDefID, unitTeam)
	writeEvent("finished", unitID, unitDefID, unitTeam)
	addBuilder(unitID, unitDefID)
end

-- A destroyed unit: whether it was finished, the attacking unit and its team (a builder
-- for a unit reclaimed, which then says "reclaimed") and the engine's weapon number
-- (negative: not a weapon, such as a crash or self-destruction).
function widget:UnitDestroyed(unitID, unitDefID, unitTeam, attackerID, attackerDefID, attackerTeam, weaponDefID)
	hitBefore[unitID] = nil
	removeBuilder(unitID)
	local _, _, _, _, buildProgress = spGetUnitHealth(unitID)
	local reclaimed = false
	if attackerID then
		local task, target = spGetUnitWorkerTask(attackerID)
		reclaimed = task == CMD_RECLAIM and target == unitID
	end
	writeEvent(
		"destroyed",
		unitID,
		unitDefID,
		unitTeam,
		format(
			',"built":%s,"by_team":%d,"by":%d%s%s',
			(buildProgress or 1) >= 1 and "true" or "false",
			attackerTeam or -1,
			attackerID or -1,
			weaponDefID and format(',"weapon":%d', weaponDefID) or "",
			reclaimed and ',"reclaimed":true' or ""
		)
	)
end

-- A factory or builder that ran out of orders: BAR's interface lists it as idle, and the
-- player's next order to it is their reaction (docs/decisions/0008).
function widget:UnitIdle(unitID, unitDefID, unitTeam)
	local unitDef = unitDefID and UnitDefs[unitDefID]
	if unitDef and (unitDef.isBuilder or unitDef.isFactory) then
		writeEvent("idle", unitID, unitDefID, unitTeam)
	end
end

function widget:UnitGiven(unitID, unitDefID, newTeam, oldTeam)
	writeEvent("given", unitID, unitDefID, newTeam, format(',"from":%d', oldTeam or -1))
end

local function sample(frame)
	if frame % DAMAGE_FRAMES == 0 and next(damageSums) then
		writeDamageSums(frame)
	end
	local snapshot = snapshotFrames > 0 and frame % snapshotFrames == 0
	if snapshot or (resourceFrames > 0 and frame % resourceFrames == 0) then
		writeResources(frame)
	end
	if snapshot then
		writeSnapshot(frame)
	end
	if workFrames > 0 and frame % workFrames == 0 then
		sampleWork(frame)
	end
	if maxFrame > 0 and frame >= maxFrame then
		finish("maxframe")
		Spring.SendCommands("quitforce")
	end
end

function widget:GameFramePost(frame)
	framePostSeen = true
	if not finished and not sampleAtFrameStart then
		sample(frame)
	end
end

function widget:GameFrame(frame)
	if finished then
		return
	end
	if not framePostSeen and frame >= 2 then
		sampleAtFrameStart = true -- GameFramePost(frame - 1) never came
	end
	if sampleAtFrameStart then
		sample(frame)
	end
end

function widget:GameOver(winners)
	finish("gameover", winners)
	Spring.SendCommands("quitforce")
end

function widget:Shutdown()
	finish("shutdown")
end
