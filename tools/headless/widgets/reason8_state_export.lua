--------------------------------------------------------------------------------
-- reason8_state_export.lua -- game state snapshots, written while a game or a
-- replay runs in spring-headless.
--
-- A replay records commands, not the world. Played back by the engine, with
-- this widget loaded as a full-view spectator, it writes what the world looked
-- like: every N seconds one line with every team's resources and every unit's
-- type, owner, position, health and build progress, plus one line per unit
-- created / finished / destroyed / given. The widget is unsynced and gives no
-- orders, so the replay stays valid.
--
-- The approach (spectator widget + headless playback at max speed) follows
-- Apex's barai_replay_export.lua (github.com/apexearth/bar-ai, GPL v2+); the
-- code here is our own.
--
-- Output: JSON lines in LuaUI/Config/reason8_state.jsonl under the write dir
-- (LuaUI/Config is one of the two folders BAR lets a user widget write to).
-- Settings come from springsettings.cfg, written by tools/headless/run.py:
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
local FORMAT_VERSION = 1

local spGetGameFrame = Spring.GetGameFrame
local spGetAllUnits = Spring.GetAllUnits
local spGetUnitDefID = Spring.GetUnitDefID
local spGetUnitTeam = Spring.GetUnitTeam
local spGetUnitPosition = Spring.GetUnitPosition
local spGetUnitHealth = Spring.GetUnitHealth
local spGetTeamResources = Spring.GetTeamResources
local floor = math.floor
local format = string.format
local concat = table.concat

local snapshotFrames = Spring.GetConfigInt("Reason8SnapshotFrames", 150)
local wantedSpeed = Spring.GetConfigInt("Reason8Speed", 0)
local maxFrame = Spring.GetConfigInt("Reason8MaxFrame", 0)
local writeEvents = Spring.GetConfigInt("Reason8Events", 1) ~= 0

local outputFile
local teams = {}
local finished = false

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
		teamParts[#teamParts + 1] = format(
			'{"team":%d,"ally":%d,"ai":%s,"side":%s,"gaia":%s}',
			team,
			allyTeam or -1,
			isAI and "true" or "false",
			jsonString(side or ""),
			team == Spring.GetGaiaTeamID() and "true" or "false"
		)
	end
	write(
		format(
			'{"t":"header","v":%d,"game":%s,"map":%s,"engine":%s,"mapx":%d,"mapz":%d,'
				.. '"replay":%s,"snapshot_frames":%d,"teams":[%s],"unitdefs":{%s}}',
			FORMAT_VERSION,
			jsonString(Game.gameName .. " " .. Game.gameVersion),
			jsonString(Game.mapName),
			jsonString(Engine.version),
			Game.mapSizeX,
			Game.mapSizeZ,
			Spring.IsReplay() and "true" or "false",
			snapshotFrames,
			concat(teamParts, ","),
			concat(unitDefNames, ",")
		)
	)
end

-- One line per snapshot. Arrays, not objects, to keep it small:
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
	write(format('{"t":"s","f":%d,"teams":[%s],"units":[%s]}', frame, concat(teamParts, ","), concat(unitParts, ",")))
end

local function finish(reason, winners)
	if finished then
		return
	end
	finished = true
	local frame = spGetGameFrame()
	if snapshotFrames > 0 then
		writeSnapshot(frame)
	end
	write(format('{"t":"end","f":%d,"reason":%s,"winners":[%s]}', frame, jsonString(reason), concat(winners or {}, ",")))
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

function widget:UnitCreated(unitID, unitDefID, unitTeam, builderID)
	writeEvent("created", unitID, unitDefID, unitTeam, builderID and format(',"by":%d', builderID))
end

function widget:UnitFinished(unitID, unitDefID, unitTeam)
	writeEvent("finished", unitID, unitDefID, unitTeam)
end

function widget:UnitDestroyed(unitID, unitDefID, unitTeam, attackerID, attackerDefID, attackerTeam)
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
