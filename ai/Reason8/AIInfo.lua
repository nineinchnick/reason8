-- Reason8: a BARb variant that plays openings learned from human replays.
--
-- The engine finds a Skirmish AI by the short name and version below. Reason8
-- needs its own short name: lobbies send only the short name, so a variant
-- that was merely another version of "BARb" would load stock BARb.
-- tools/variant/build.py reads the short name and version from this file to
-- name the install folder: AI/Skirmish/<shortName>/<version>/.

local infos = {
	{
		key = 'shortName',
		value = 'Reason8',
		desc = 'machine conform name.',
	},
	{
		key = 'version',
		value = '0.1',
	},
	{
		key = 'name',
		value = 'Reason8',
		desc = 'human readable name.',
	},
	{
		key = 'description',
		value = 'BARb with openings learned from human replays.',
		desc = 'tooltip.',
	},
	{
		key = 'url',
		value = 'https://github.com/nineinchnick/reason8',
		desc = 'URL with more detailed info about the AI',
	},
	{
		key = 'loadSupported',
		value = 'yes',
		desc = 'whether this AI supports loading or not',
	},
	{
		key = 'interfaceShortName',
		value = 'C',
		desc = 'the shortName of the AI interface this AI needs',
	},
	{
		key = 'interfaceVersion',
		value = '0.1',
		desc = 'the minimum version of the AI interface this AI needs',
	},
}

return infos
