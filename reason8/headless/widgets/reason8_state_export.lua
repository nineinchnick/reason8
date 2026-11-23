--------------------------------------------------------------------------------
-- reason8_state_export.lua -- game state snapshots, written while a game or a
-- replay runs in spring-headless.
--
-- A replay records commands, not the world. Played back by the engine, with
-- this widget loaded as a full-view spectator, it writes what the world looked
-- like: every N seconds one line with every team's resources and every unit's
-- type, owner, position, health and build progress, plus one line per unit
-- created / finished / destroyed / given, and the damage enemies do to each
-- other. The widget is unsynced and gives no orders, so the replay stays valid.
--
-- The approach (spectator widget + headless playback at max speed) follows
-- Apex's barai_replay_export.lua (github.com/apexearth/bar-ai, GPL v2+); the
-- code here is our own.
--
-- Output: JSON lines in LuaUI/Config/reason8_state.jsonl under the write dir
-- (LuaUI/Config is one of the two folders BAR lets a user widget write to).
-- Settings come from springsettings.cfg, written by reason8/headless/run.py:
--   Reason8SnapshotFrames  frames between snapshots (default 150 = 5 s, 0 = off)
--   Reason8Speed           game speed to ask for (default 0 = leave alone)
--   Reason8MaxFrame        quit at this frame (default 0 = only at game over)
--   Reason8Events          1 = also write per-unit event lines (default 1)
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
local FORMAT_VERSION = 3 -- 2: hit and damage lines, wind; 3: exact attacker

local spGetGameFrame = Spring.GetGameFrame
local spGetAllUnits = Spring.GetAllUnits
local spGetUnitDefID = Spring.GetUnitDefID
local spGetUnitTeam = Spring.GetUnitTeam
local spGetUnitPosition = Spring.GetUnitPosition
local spGetUnitHealth = Spring.GetUnitHealth
local spGetTeamResources = Spring.GetTeamResources
local spGetUnitLastAttacker = Spring.GetUnitLastAttacker
local spGetWind = Spring.GetWind
local floor = math.floor
local format = string.format
local concat = table.concat

local snapshotFrames = Spring.GetConfigInt("Reason8SnapshotFrames", 150)
local wantedSpeed = Spring.GetConfigInt("Reason8Speed", 0)
local maxFrame = Spring.GetConfigInt("Reason8MaxFrame", 0)
local writeEvents = Spring.GetConfigInt("Reason8Events", 1) ~= 0

local DAMAGE_FRAMES = 30 -- damage between teams is summed over this many frames

local outputFile
local teams = {}
local allyTeamOfTeam = {}
local gaiaTeam = Spring.GetGaiaTeamID()
local finished = false
-- damage by enemies: who has hit which unit already, and the sums not yet written
local hitBefore = {} -- [unitID] = { [attackerTeam] = true }
local damageSums = {} -- [victimTeam * 256 + attackerTeam] = { hits, damage }

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
	local unitDefNames = {}
	for unitDefID, unitDef in pairs(UnitDefs) do
		unitDefNames[#unitDefNames + 1] = format("%s:%s", jsonString(unitDefID), jsonString(unitDef.name))
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
				.. '"replay":%s,"snapshot_frames":%d,"wind_min":%.1f,"wind_max":%.1f,"tidal":%.1f,'
				.. '"teams":[%s],"unitdefs":{%s}}',
			FORMAT_VERSION,
			jsonString(Game.gameName .. " " .. Game.gameVersion),
			jsonString(Game.mapName),
			jsonString(Engine.version),
			Game.mapSizeX,
			Game.mapSizeZ,
			Spring.IsReplay() and "true" or "false",
			snapshotFrames,
			Game.windMin or -1,
			Game.windMax or -1,
			Game.tidal or -1,
			concat(teamParts, ","),
			concat(unitDefNames, ",")
		)
	)
end

-- One line per snapshot, with the wind strength at that moment (it changes all
-- the time, and with it what a wind turbine makes). Arrays, not objects, to
-- keep it small:
--   teams: [team, metal, metalStorage, metalIncome, metalExpense,
--           energy, energyStorage, energyIncome, energyExpense]
--   units: [unitID, unitDefID, team, x, z, health%, build%]
local function writeSnapshot(frame)
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
	local unitParts = {}
	local units = spGetAllUnits()
	for i = 1, #units do
		local unitID = units[i]
		local unitDefID = spGetUnitDefID(unitID)
		local x, _, z = spGetUnitPosition(unitID)
		if unitDefID and x then
			local health, maxHealth, _, _, buildProgress = spGetUnitHealth(unitID)
			local healthPercent = (health and maxHealth and maxHealth > 0) and floor(100 * health / maxHealth) or 0
			unitParts[#unitParts + 1] = format(
				"[%d,%d,%d,%d,%d,%d,%d]",
				unitID,
				unitDefID,
				spGetUnitTeam(unitID) or -1,
				x,
				z,
				healthPercent < 0 and 0 or healthPercent,
				floor(100 * (buildProgress or 1))
			)
		end
	end
	local _, _, _, windStrength = spGetWind()
	write(
		format(
			'{"t":"s","f":%d,"wind":%.2f,"teams":[%s],"units":[%s]}',
			frame,
			windStrength or -1,
			concat(teamParts, ","),
			concat(unitParts, ",")
		)
	)
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
	finished = true
	local frame = spGetGameFrame()
	writeDamageSums(frame)
	if snapshotFrames > 0 then
		writeSnapshot(frame)
	end
	write(
		format(
			'{"t":"end","f":%d,"reason":%s,"winners":[%s],"attackers":%s}',
			frame,
			jsonString(reason),
			concat(winners or {}, ","),
			jsonString(attackerSource)
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
	if wantedSpeed > 0 then
		-- a replay plays at 1x unless told otherwise; min = max pins the speed
		Spring.SendCommands("setmaxspeed " .. wantedSpeed, "setminspeed " .. wantedSpeed)
	end
	Spring.Echo(format("[R8] state export on: every %d frames, speed %d, max frame %d", snapshotFrames, wantedSpeed, maxFrame))
end

function widget:UnitCreated(unitID, unitDefID, unitTeam, builderID)
	writeEvent("created", unitID, unitDefID, unitTeam, builderID and format(',"by":%d', builderID))
end

function widget:UnitFinished(unitID, unitDefID, unitTeam)
	writeEvent("finished", unitID, unitDefID, unitTeam)
end

function widget:UnitDestroyed(unitID, unitDefID, unitTeam, attackerID, attackerDefID, attackerTeam)
	hitBefore[unitID] = nil
	local _, _, _, _, buildProgress = spGetUnitHealth(unitID)
	writeEvent(
		"destroyed",
		unitID,
		unitDefID,
		unitTeam,
		format(',"built":%s,"by_team":%d', (buildProgress or 1) >= 1 and "true" or "false", attackerTeam or -1)
	)
end

function widget:UnitGiven(unitID, unitDefID, newTeam, oldTeam)
	writeEvent("given", unitID, unitDefID, newTeam, format(',"from":%d', oldTeam or -1))
end

function widget:GameFrame(frame)
	if finished then
		return
	end
	if frame % DAMAGE_FRAMES == 0 and next(damageSums) then
		writeDamageSums(frame)
	end
	if snapshotFrames > 0 and frame % snapshotFrames == 0 then
		writeSnapshot(frame)
	end
	if maxFrame > 0 and frame >= maxFrame then
		finish("maxframe")
		Spring.SendCommands("quitforce")
	end
end

function widget:GameOver(winners)
	finish("gameover", winners)
	Spring.SendCommands("quitforce")
end

function widget:Shutdown()
	finish("shutdown")
end
